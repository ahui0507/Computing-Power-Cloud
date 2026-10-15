"""按用户隔离的持久化文件目录，与 GPU Pod 的共享卷子目录一致。"""

import asyncio
import os
import uuid
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import HTTPException

from app.core.config import settings
from app.services.storage_quota_service import StorageQuotaService
from app.core.exceptions import (
    AuthorizationError,
    ResourceConflictError,
    ResourceNotFoundError,
)


class StorageService:
    @staticmethod
    def user_root(user_id: int) -> Path:
        if user_id < 1:
            raise AuthorizationError("无效用户")
        base = Path(settings.STORAGE_ROOT).resolve()
        base.mkdir(parents=True, exist_ok=True)
        directory = base / f"user_{user_id}"
        if directory.is_symlink():
            raise AuthorizationError("用户工作目录不能为符号链接")
        directory.mkdir(mode=0o770, exist_ok=True)
        if os.name == "posix":
            if directory.stat().st_gid != settings.WORKSPACE_GID:
                os.chown(directory, -1, settings.WORKSPACE_GID)
            directory.chmod(0o2770)
        return directory

    @staticmethod
    def _parts(value: str, *, allow_root=False):
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts:
            raise AuthorizationError("文件路径必须位于自己的工作目录")
        if any(ord(character) < 32 for character in value):
            raise AuthorizationError("文件路径包含无效字符")
        parts = tuple(part for part in path.parts if part not in ("", "."))
        if not parts and not allow_root:
            raise ResourceConflictError("不能操作工作目录本身")
        return parts

    @staticmethod
    def resolve_path(user_id: int, value: str, *, allow_root=False) -> Path:
        root = StorageService.user_root(user_id)
        parts = StorageService._parts(value, allow_root=allow_root)
        result = root.joinpath(*parts)
        for parent in (result, *result.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise AuthorizationError("不允许通过符号链接访问文件")
        resolved = result.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise AuthorizationError("文件路径超出用户工作目录")
        return resolved

    @staticmethod
    @contextmanager
    def _parent(user_id: int, value: str):
        # Linux 使用目录描述符固定祖先目录，避免校验后的符号链接替换。
        parts = StorageService._parts(value)
        path = StorageService.resolve_path(user_id, value)
        descriptor = None
        try:
            if os.open in os.supports_dir_fd:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                descriptor = os.open(StorageService.user_root(user_id), flags)
                for part in parts[:-1]:
                    child = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
            yield path, descriptor
        except FileNotFoundError as exc:
            raise ResourceNotFoundError("File or folder") from exc
        except OSError as exc:
            if exc.errno in (40, 20):  # ELOOP, ENOTDIR
                raise AuthorizationError("文件路径包含符号链接或无效目录") from exc
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    async def upload_file(db, user_id: int, file, folder: str = "") -> str:
        name = file.filename or ""
        if not name or len(StorageService._parts(name)) != 1:
            raise AuthorizationError("上传文件名不能包含目录")
        StorageService._parts(folder, allow_root=True)
        relative = str(PurePosixPath(folder) / name)
        StorageQuotaService.writable(db, user_id, max(1, getattr(file, "size", None) or 1))
        with StorageQuotaService.write_guard():
            with StorageService._parent(user_id, relative) as (destination, parent_fd):
                temporary_name = f".upload-{uuid.uuid4().hex}"
                temporary_path = destination.parent / temporary_name
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(
                    temporary_name if parent_fd is not None else temporary_path,
                    flags,
                    0o660,
                    **({"dir_fd": parent_fd} if parent_fd is not None else {}),
                )
                try:
                    total = 0
                    with os.fdopen(descriptor, "wb") as stream:
                        while chunk := await file.read(1024 * 1024):
                            total += len(chunk)
                            if total > settings.MAX_UPLOAD_BYTES:
                                raise HTTPException(413, "文件超过上传大小限制")
                            await asyncio.to_thread(stream.write, chunk)
                        await asyncio.to_thread(stream.flush)
                        await asyncio.to_thread(os.fsync, stream.fileno())
                    if parent_fd is not None:
                        os.replace(
                            temporary_name,
                            destination.name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                        )
                    else:
                        temporary_path.replace(destination)
                finally:
                    try:
                        os.unlink(
                            temporary_name if parent_fd is not None else temporary_path,
                            **({"dir_fd": parent_fd} if parent_fd is not None else {}),
                        )
                    except FileNotFoundError:
                        pass
        return relative

    @staticmethod
    async def list_files(db, user_id: int, folder: str = ""):
        files = []
        marker = str(PurePosixPath(folder) / ".list-marker")
        with StorageService._parent(user_id, marker) as (path, descriptor):
            directory = path.parent
            names = os.listdir(descriptor) if descriptor is not None else os.listdir(directory)
            for name in sorted(names, key=str.lower):
                info = (
                    os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if descriptor is not None
                    else (directory / name).lstat()
                )
                if stat.S_ISLNK(info.st_mode) or name.startswith(".upload-"):
                    continue
                files.append(
                    {
                        "name": name,
                        "path": str(PurePosixPath(folder) / name),
                        "size": info.st_size if stat.S_ISREG(info.st_mode) else 0,
                        "type": "file" if stat.S_ISREG(info.st_mode) else "folder",
                    }
                )
        return files

    @staticmethod
    def open_download(user_id: int, value: str):
        with StorageService._parent(user_id, value) as (path, parent_fd):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            descriptor = os.open(
                path.name if parent_fd is not None else path,
                flags,
                **({"dir_fd": parent_fd} if parent_fd is not None else {}),
            )
            stream = os.fdopen(descriptor, "rb")
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                stream.close()
                raise ResourceConflictError("只能下载文件")
            return stream, path.name

    @staticmethod
    async def delete_file(db, user_id: int, path: str):
        with StorageService._parent(user_id, path) as (target, parent_fd):
            if not target.exists():
                raise ResourceNotFoundError("File")
            try:
                operation = os.rmdir if target.is_dir() else os.unlink
                operation(
                    target.name if parent_fd is not None else target,
                    **({"dir_fd": parent_fd} if parent_fd is not None else {}),
                )
            except OSError as exc:
                if exc.errno in (39, 66, 145):  # ENOTEMPTY
                    raise ResourceConflictError("文件夹非空，不能删除") from exc
                raise
