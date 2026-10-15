#!/usr/bin/env python3
"""平台迁移入口：配置、发布包、离线镜像、停机备份恢复及部署验收。入口 Python 3.8+，后端 Python 3.10。"""
import argparse
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(args, *, cwd=None, input=None, stdout=None):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, input=input,
                            stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # 子进程可能输出数据库 URL、令牌等；只报告程序名称和退出码。
        raise ValueError(f"{Path(str(args[0])).name} 执行失败（退出码 {result.returncode}），请在主机上核对依赖和服务状态")
    return result.stdout or b""


def write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    path.chmod(mode)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def directory(path):
    value = str(path)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in PurePosixPath(value).parts:
        raise ValueError(f"需要不含空格、特殊字符和上级引用的 Linux 绝对路径: {value}")
    if value in {"/", "/etc", "/usr", "/var", "/home", "/srv", "/opt", "/mnt", "/var/www"}:
        raise ValueError(f"不能把系统目录作为迁移目标: {value}")
    return value


def load_site(path):
    site = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if site.get("format") != 1:
        raise ValueError("未知配置版本")
    for key in ("service_user", "service_group", "backend_service", "database_name", "namespace"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", site[key]):
            raise ValueError(f"无效配置: {key}")
    for key in ("release_root", "current_link", "web_link", "workspace_root", "image_store_root", "kubeconfig"):
        directory(site[key])
    roots = [PurePosixPath(site[key]) for key in ("release_root", "workspace_root", "image_store_root")]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError("发布目录、个人文件和镜像存储不能重叠")
    url = urllib.parse.urlsplit(site["public_url"])
    if url.scheme != "http" or not url.hostname or url.username or url.query or url.fragment or url.path not in ("", "/") or url.port not in (None, 80):
        raise ValueError("本入口生成校内 HTTP 80 部署；public_url 需为 http://主机，HTTPS 见迁移手册")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", url.hostname):
        raise ValueError("无效访问主机名")
    upstream = urllib.parse.urlsplit(site["traefik_upstream"])
    if upstream.scheme != "http" or not upstream.hostname or upstream.username or upstream.path or upstream.query or upstream.fragment:
        raise ValueError("traefik_upstream 需为 http://IP:NodePort")
    ipaddress.ip_address(upstream.hostname)
    if not upstream.port or not 1 <= upstream.port <= 65535:
        raise ValueError("无效 Traefik 端口")
    nodes = [site["control"], *site["workers"]]
    if not site["workers"] or len({node["id"] for node in nodes}) != len(nodes) or len({node["name"] for node in nodes}) != len(nodes):
        raise ValueError("需要至少一个计算节点，节点 ID 和名称不能重复")
    for node in nodes:
        if type(node["id"]) is not int or node["id"] <= 0 or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", node["name"]):
            raise ValueError("无效节点 ID 或名称")
        ipaddress.IPv4Address(node["ip"])
    ipaddress.IPv4Address(site["control"].get("nfs_ip", site["control"]["ip"]))
    for worker in site["workers"]:
        directory(worker["image_mount"])
        if type(worker["agent_port"]) is not int or not 1024 <= worker["agent_port"] <= 65535:
            raise ValueError("无效镜像代理端口")
        if worker["agent_port"] != 8091:
            raise ValueError("现有镜像代理监听 8091，请将 agent_port 设为 8091")
    if type(site["workspace_gid"]) is not int or site["workspace_gid"] < 0:
        raise ValueError("无效工作目录组 ID")
    return site


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("环境配置需采用 KEY=value 格式")
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        values[key] = value
    return values


def env_text(values):
    for value in values.values():
        if any(char in str(value) for char in ("\n", "\r", "'")):
            raise ValueError("配置值不能包含换行或单引号；数据库密码特殊字符应进行 URL 编码")
    return "".join(f"{key}='{value}'\n" for key, value in values.items())


def render(site, output, backend_env=None, monitor_tokens=None):
    output = Path(output)
    if output.exists():
        raise ValueError("配置输出目录已存在，请选择新目录，避免覆盖已有密钥")
    output.mkdir(parents=True, mode=0o700)
    values = read_env(backend_env or ROOT / "backend/.env.example")
    values.update({"STORAGE_ROOT": site["workspace_root"], "IMAGE_STORE_ROOT": site["image_store_root"],
                   "WORKSPACE_GID": str(site["workspace_gid"]), "K8S_CONFIG_PATH": site["kubeconfig"],
                   "K8S_NAMESPACE": site["namespace"], "CONTROL_NODE_ID": str(site["control"]["id"]),
                   "INGRESS_HOST": urllib.parse.urlsplit(site["public_url"]).hostname,
                   "INGRESS_ENABLED": "true", "INGRESS_USE_TLS": "false", "SSH_ENABLED": "true",
                   "CORS_ORIGINS": site["public_url"].rstrip("/"), "K8S_IMAGE_PULL_POLICY": "Never",
                   "WORKER_AGENT_URLS": json.dumps({worker["name"]: f'http://{worker["ip"]}:8091' for worker in site["workers"]}),
                   "AUTO_INIT_DATABASE": "false"})
    # 使用配置域名作为 Jupyter 和 SSH 入口，而非内网 control 地址。
    values["CONTROL_NODE_ID"] = ""
    write(output / "backend.env", env_text(values))
    write(output / "site.json", json.dumps(site, ensure_ascii=False, indent=2))
    public = urllib.parse.urlsplit(site["public_url"])
    nginx = (ROOT / "deploy/nginx/computing-platform.conf.example").read_text(encoding="utf-8")
    nginx = nginx.replace("listen 80 default_server;", f"listen {public.port or 80} default_server;")
    nginx = nginx.replace("server_name REPLACE_NODE_INTERNAL_IP platform.local;", f"server_name {public.hostname};")
    nginx = nginx.replace("root /var/www/platform-current;", f'root {site["web_link"]};')
    nginx = nginx.replace("http://REPLACE_NODE_INTERNAL_IP:31663", site["traefik_upstream"])
    write(output / "nginx.conf", nginx, 0o644)
    write(output / "backend.service", f'''[Unit]
Description=Computing platform backend
After=network-online.target mysql.service redis-server.service
Wants=network-online.target
[Service]
User={site['service_user']}
Group={site['service_group']}
WorkingDirectory={site['current_link']}/backend
ExecStart={site['current_link']}/backend/.venv/bin/python scripts/start_backend.py
Restart=always
RestartSec=5
UMask=0027
[Install]
WantedBy=multi-user.target
''', 0o644)
    pv = (ROOT / "deploy/kubernetes/cluster/workspaces.yaml").read_text(encoding="utf-8")
    nfs_ip = site["control"].get("nfs_ip", site["control"]["ip"])
    pv = pv.replace("server: NFS_SERVER_IP", f'server: {nfs_ip}').replace("path: /data/workspaces", f'path: {site["workspace_root"]}')
    pv = pv.replace("namespace: default", f'namespace: {site["namespace"]}')
    write(output / "workspaces.yaml", pv, 0o644)
    clients = " ".join(f'{worker["ip"]}(rw,sync,no_subtree_check,root_squash,anonuid={site["workspace_gid"]},anongid={site["workspace_gid"]})' for worker in site["workers"])
    write(output / "nfs.exports", f'{site["workspace_root"]} {clients}\n{site["image_store_root"]} {clients}\n', 0o644)
    monitor_tokens = monitor_tokens or {}
    for node in [site["control"], *site["workers"]]:
        write(output / node["name"] / "monitor.env", env_text({"PLATFORM_MONITOR_URL": site["public_url"].rstrip("/") + "/api/internal/telemetry",
            "PLATFORM_MONITOR_NODE": node["name"], "PLATFORM_MONITOR_TOKEN": monitor_tokens.get(str(node["id"]), "REPLACE_WITH_EXISTING_NODE_TOKEN"),
            "PLATFORM_MONITOR_INTERVAL": "15"}))
    for worker in site["workers"]:
        worker_dir = output / worker["name"]
        write(worker_dir / "agent.env", env_text({"WORKER_AGENT_TOKEN": values.get("WORKER_AGENT_TOKEN", ""),
            "WORKER_AGENT_BIND": worker["ip"], "IMAGE_STORE_ROOT": worker["image_mount"]}))
        unit = (ROOT / "deploy/worker-agent/platform-worker-agent.service").read_text(encoding="utf-8")
        write(worker_dir / "agent.service", unit.replace("RequiresMountsFor=/mnt/platform-images", f'RequiresMountsFor={worker["image_mount"]}'), 0o644)
        write(worker_dir / "fstab", f'{nfs_ip}:{site["image_store_root"]} {worker["image_mount"]} nfs rw,hard,timeo=600,retrans=2,_netdev 0 0\n', 0o644)
    return output


def backend_state(backend, command="inventory", site=None, apply=False):
    backend = Path(backend).resolve()
    args = [backend / ".venv/bin/python", backend / "scripts/migration_state.py", command]
    if site:
        args += ["--site", Path(site).resolve()]
    if apply:
        args += ["--apply"]
    return json.loads(run(args, cwd=backend))


def stopped(service):
    state = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True).stdout.strip()
    if state not in {"inactive", "failed", "unknown"}:
        raise ValueError("后端服务尚未停止；请先保存并结束实例，再停后端进行迁移")
    return state


def mysql_args(program, args, site):
    result = [program]
    if args.mysql_defaults:
        result.append("--defaults-extra-file=" + str(Path(args.mysql_defaults).resolve()))
    return result + ["--host", args.mysql_host, "--port", str(args.mysql_port), "--user", args.mysql_user]


def empty(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise ValueError(f"目标必须为空目录且不能是符号链接: {path}")


def seal(folder, kind, extra=None):
    folder = Path(folder)
    files = {str(path.relative_to(folder)).replace("\\", "/"): digest(path)
             for path in sorted(folder.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    manifest = {"format": 1, "kind": kind, "files": files, **(extra or {})}
    write(folder / "manifest.json", json.dumps(manifest, indent=2))
    return manifest


def verify(folder, kind=None):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or manifest.get("kind") not in {"release", "backup"} or (kind and manifest.get("kind") != kind):
        raise ValueError("迁移包类型或格式不匹配")
    for name, expected in manifest["files"].items():
        member = PurePosixPath(name)
        path = folder / name
        if member.is_absolute() or ".." in member.parts or path.is_symlink() or not within(path, folder) or not path.is_file():
            raise ValueError("迁移包包含无效路径")
        if digest(path) != expected:
            raise ValueError(f"校验失败: {name}")
    required = {"source.tar.gz", "frontend.tar.gz"} if manifest["kind"] == "release" else {"database.sql.gz", "workspaces.tar.gz", "images.tar.gz", "backend.env", "inventory.json", "site.json"}
    if not required.issubset(manifest["files"]):
        raise ValueError("迁移包缺少必要内容")
    return manifest


def within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def extract(archive, target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    def safe(member, destination):
        if PurePosixPath(member.name).is_absolute() or ".." in PurePosixPath(member.name).parts:
            raise ValueError("归档包含越界路径")
        if not within(Path(destination) / member.name, destination):
            raise ValueError("归档目标越界")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError("归档含非文件、目录或链接的条目")
        if member.issym() or member.islnk():
            base = Path(destination) / Path(member.name).parent if member.issym() else Path(destination)
            if Path(member.linkname).is_absolute() or not within(base / member.linkname, destination):
                raise ValueError("归档链接越界")
        filtered = tarfile.data_filter(member, destination) if hasattr(tarfile, "data_filter") else member
        if filtered is not None:
            # data_filter 核对每次实际写入路径；保留 NFS 所需数值属主和目录组继承。
            filtered.uid, filtered.gid = member.uid, member.gid
            filtered.mode = member.mode & 0o3777
        return filtered
    with tarfile.open(archive) as source:
        if hasattr(tarfile, "data_filter"):
            source.extractall(target, numeric_owner=True, filter=safe)
        else:
            # Ubuntu 20.04 的 Python 3.8 尚无 PEP 706；按实际写入顺序逐条核对路径和链接。
            for member in source:
                source.extract(safe(member, str(target)), target, numeric_owner=True)


def package(args):
    output = Path(args.output).resolve()
    empty(output)
    revision = run(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    if run(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise ValueError("发布包只接受已提交且干净的工作区；测试用暂存目录请用 git archive 创建")
    # 从当前干净提交构建，避免将上一版本的 dist 放入新发布包。
    run([shutil.which("npm") or "npm", "run", "build"], cwd=ROOT / "frontend")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        raise ValueError("请先执行 npm ci、npm test 和 npm run build")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    run(["git", "archive", "--format=tar.gz", "--output", output / "source.tar.gz", revision], cwd=ROOT)
    with tarfile.open(output / "frontend.tar.gz", "w:gz") as archive:
        archive.add(dist, arcname="dist")
    if args.wheels:
        shutil.copytree(args.wheels, output / "wheels")
    seal(output, "release", {"revision": revision})
    print("已创建源码、前端产物及校验清单；依赖轮子: " + ("已包含" if args.wheels else "未包含，安装时需联网"))


def backup(args, site):
    state = backend_state(args.backend)
    if state["database_name"] != site["database_name"]:
        raise ValueError("配置与后端连接的数据库名不一致")
    if any(state["unfinished"].values()):
        raise ValueError("仍有未完成实例、资源操作、GPU 预留或镜像任务，不能生成迁移备份")
    output = Path(args.output).resolve()
    empty(output)
    for key in ("workspace_root", "image_store_root"):
        source = Path(site[key]).resolve()
        if source == output or source in output.parents or output in source.parents or not source.is_dir():
            raise ValueError("备份输出不能与存储重叠，且源存储必须存在")
    print("备份计划：数据库、个人目录（含隐藏密钥）、个人镜像和任务记录、后端配置、额外采集配置")
    if not args.execute:
        print("预览完成；实际迁移需先停后端，再加 --execute")
        return
    stopped(site["backend_service"])
    unit = run(["systemctl", "show", site["backend_service"], "-p", "WorkingDirectory", "--value"]).decode().strip()
    if not unit or Path(unit).resolve() != Path(args.backend).resolve():
        raise ValueError("停机服务的工作目录与待备份后端不一致")
    state = backend_state(args.backend)
    if any(state["unfinished"].values()):
        raise ValueError("停机后复核仍有未结束工作，备份中止")
    if state.get("database_server_uuid"):
        actual = run(mysql_args("mysql", args, site) + ["--batch", "--skip-column-names", "-e", "SELECT @@server_uuid"]).decode().strip()
        if actual != state["database_server_uuid"]:
            raise ValueError("备份客户端连接的 MySQL 与后端数据库不是同一服务器")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with gzip.open(output / "database.sql.gz", "wb") as stream:
        # gzip 的 fileno 不能作为 subprocess 输出，否则产生伪 gzip 文件。
        with tempfile.TemporaryFile() as sql:
            run(mysql_args("mysqldump", args, site) + ["--single-transaction", "--hex-blob", "--no-tablespaces", site["database_name"]], stdout=sql)
            sql.seek(0)
            shutil.copyfileobj(sql, stream)
    for key, name in (("workspace_root", "workspaces.tar.gz"), ("image_store_root", "images.tar.gz")):
        run(["tar", "--numeric-owner", "-czpf", output / name, "-C", site[key], "."])
    shutil.copyfile(Path(args.backend) / ".env", output / "backend.env")
    (output / "backend.env").chmod(0o600)
    if args.extra_secrets:
        with tarfile.open(output / "extra-secrets.tar.gz", "w:gz") as archive:
            archive.add(args.extra_secrets, arcname="secrets")
    write(output / "inventory.json", json.dumps(state, ensure_ascii=False, indent=2))
    write(output / "site.json", json.dumps(site, ensure_ascii=False, indent=2))
    seal(output, "backup")
    print("迁移备份完成，目录包含运行时密钥，权限为 700；请安全传输并单独携带计算节点公共镜像包")


def restore(args, site):
    manifest = verify(args.bundle, "backup")
    original_site = load_site(Path(args.bundle) / "site.json")
    if original_site["workspace_gid"] != site["workspace_gid"]:
        raise ValueError("迁移须保持共享目录的原数值组 ID；改组需单独完成权限转换")
    for key in ("workspace_root", "image_store_root"):
        empty(site[key])
    destination = Path(args.secrets_output).resolve()
    empty(destination)
    for key in ("workspace_root", "image_store_root"):
        root = Path(site[key]).resolve()
        if root == destination or root in destination.parents or destination in root.parents:
            raise ValueError("恢复密钥目录不能与业务存储重叠")
    print("恢复计划：校验完整迁移备份，仅写入空数据库和空目录；不启动服务")
    if not args.execute:
        return
    stopped(site["backend_service"])
    client = mysql_args("mysql", args, site) + ["--batch", "--skip-column-names", site["database_name"]]
    if run(client + ["-e", "SHOW TABLES"]).strip():
        raise ValueError("目标数据库非空，拒绝恢复")
    # 先在同一文件系统的临时目录完整解包，越界或损坏归档不会先改数据库。
    staged = []
    try:
        for target, archive in ((Path(site["workspace_root"]), "workspaces.tar.gz"),
                                (Path(site["image_store_root"]), "images.tar.gz"), (destination, None)):
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".platform-restore-", dir=target.parent))
            staged.append((temporary, target))
            if archive:
                extract(Path(args.bundle) / archive, temporary)
            else:
                shutil.copyfile(Path(args.bundle) / "backend.env", temporary / "backend.env")
                (temporary / "backend.env").chmod(0o600)
                if "extra-secrets.tar.gz" in manifest["files"]:
                    extract(Path(args.bundle) / "extra-secrets.tar.gz", temporary)
        # SQL 失败保留空目标和错误现场；不会清空数据库或自动重试覆盖。
        with gzip.open(Path(args.bundle) / "database.sql.gz", "rb") as sql:
            with tempfile.TemporaryFile() as expanded:
                shutil.copyfileobj(sql, expanded)
                expanded.seek(0)
                result = subprocess.run(client, stdin=expanded, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if result.returncode:
                    raise ValueError("数据库恢复失败；目标可能有部分数据，请核对后换用新的空数据库重试")
        for temporary, target in staged:
            empty(target)
            if target.exists():
                target.rmdir()
            temporary.rename(target)
    finally:
        for temporary, _ in staged:
            if temporary.exists():
                shutil.rmtree(temporary)
    print("恢复完成，服务保持停止；请修改恢复的数据库连接并重新生成新站点配置，再核对节点映射")


def normalized_image(value):
    first = value.split("/")[0]
    if "/" not in value:
        return "docker.io/library/" + value
    if "." not in first and ":" not in first and first != "localhost":
        return "docker.io/" + value
    return value


def validate_oci(path):
    """核对 OCI 归档完整性及各层摘要，避免为截断的导出生成有效校验文件。"""
    with tarfile.open(path) as archive:
        files = {member.name.lstrip("./"): member for member in archive if member.isfile()}
        if not {"oci-layout", "index.json"}.issubset(files):
            raise ValueError("镜像包不是完整 OCI 归档")
        for name, member in files.items():
            if name.startswith("blobs/sha256/"):
                actual = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        actual.update(chunk)
                if actual.hexdigest() != name.split("/")[-1]:
                    raise ValueError("OCI blob 摘要不匹配")
        def descriptors(document):
            for item in document.get("manifests", []) + document.get("layers", []) + ([document["config"]] if "config" in document else []):
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]):
                    raise ValueError("OCI 描述符摘要不受支持")
                name = "blobs/sha256/" + item["digest"].split(":")[1]
                if name not in files or files[name].size != item["size"]:
                    raise ValueError("OCI 归档缺少引用内容")
                if "manifest" in item.get("mediaType", "") or "index" in item.get("mediaType", ""):
                    descriptors(json.load(archive.extractfile(files[name])))
        descriptors(json.load(archive.extractfile(files["index.json"])))


def node_images(args, site):
    worker = next((row for row in site["workers"] if row["name"] == args.worker), None)
    if worker is None:
        raise ValueError("未知计算节点")
    if args.command == "export-images":
        state = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        refs = sorted({normalized_image(row["ref"]) for row in state["images"] if row["visibility"] == "public" and row["status"] == "ready" and not row["snapshot_id"]})
        if not refs:
            raise ValueError("没有待导出的可用公共镜像")
        print("公共镜像导出计划：" + ", ".join(refs))
        if args.execute:
            target = Path(args.output)
            if target.exists():
                raise ValueError("镜像归档已存在")
            target.parent.mkdir(parents=True, exist_ok=True)
            run(["k3s", "ctr", "-n", "k8s.io", "images", "export", "--local", "--platform", "linux/amd64", target, *refs])
            validate_oci(target)
            write(str(target) + ".sha256", digest(target) + "\n")
    else:
        archive = Path(args.archive)
        if digest(archive) != Path(str(archive) + ".sha256").read_text().strip():
            raise ValueError("公共镜像包校验失败")
        validate_oci(archive)
        print("镜像导入计划：公共镜像包，以及此节点关联的 ready 个人镜像 OCI 归档")
        state = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        personal = []
        for image in state["images"]:
            if image["snapshot_id"] and image["status"] == "ready" and image["source_node_id"] == worker["id"]:
                if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", image["snapshot_id"]) or type(image["owner_id"]) is not int:
                    raise ValueError("无效个人镜像归档路径")
                path = Path(worker["image_mount"]) / f'user_{image["owner_id"]}' / (image["snapshot_id"] + ".oci.tar")
                if not path.is_file():
                    raise ValueError("缺少个人镜像归档")
                validate_oci(path)
                personal.append(path)
        if args.execute:
            for path in [archive, *personal]:
                run(["k3s", "ctr", "-n", "k8s.io", "images", "import", "--platform", "linux/amd64", path])
            print(f"已导入公共包和 {len(personal)} 个个人镜像")


def install_control(args, site):
    manifest = verify(args.bundle, "release")
    generated = Path(args.generated).resolve()
    if load_site(generated / "site.json") != site:
        raise ValueError("生成配置与站点不一致")
    values = read_env(generated / "backend.env")
    if urllib.parse.urlsplit(values.get("DATABASE_URL", "")).path.lstrip("/") != site["database_name"]:
        raise ValueError("后端连接的数据库名与目标站点不一致")
    if len(values.get("SECRET_KEY", "")) < 32 and not (Path(site["workspace_root"]) / ".platform-secret").is_file():
        raise ValueError("请保留原 SECRET_KEY 或工作目录中的 .platform-secret；新安装需先准备持久化密钥")
    if len(values.get("WORKER_AGENT_TOKEN", "")) < 24:
        raise ValueError("需要完整镜像代理凭据")
    revision = manifest.get("revision", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("无效发布编号")
    release = Path(site["release_root"]) / revision
    empty(release)
    print("控制节点安装计划：独立 Python 环境、源码/前端、NFS/PVC、Nginx/systemd；保留停止状态")
    if not args.execute:
        return
    stopped(site["backend_service"])
    for program in (args.python, "nginx", "exportfs", "kubectl", "systemctl", "tar"):
        if not shutil.which(program):
            raise ValueError(f"缺少前置依赖: {program}")
    version = run([args.python, "-c", "import sys;print('.'.join(map(str,sys.version_info[:2])))"]).decode().strip()
    if version != "3.10":
        raise ValueError("当前已验收后端依赖需 Python 3.10，请指定 --python")
    extract(Path(args.bundle) / "source.tar.gz", release)
    extract(Path(args.bundle) / "frontend.tar.gz", release / "frontend")
    run([args.python, "-m", "venv", release / "backend/.venv"])
    pip = [release / "backend/.venv/bin/python", "-m", "pip", "install"]
    if (Path(args.bundle) / "wheels").is_dir():
        pip += ["--no-index", "--find-links", Path(args.bundle).resolve() / "wheels"]
    run(pip + ["-r", release / "backend/requirements.txt"])
    shutil.copyfile(generated / "backend.env", release / "backend/.env")
    (release / "backend/.env").chmod(0o600)
    write(release / "REVISION", revision + "\n", 0o644)
    run(["chown", "-R", f'{site["service_user"]}:{site["service_group"]}', release])
    import pwd
    owner = pwd.getpwnam(site["service_user"])
    for key in ("workspace_root", "image_store_root"):
        storage = Path(site[key])
        if not storage.exists():
            storage.mkdir(parents=True)
            os.chown(storage, owner.pw_uid, site["workspace_gid"])
            storage.chmod(0o2770)
    for link, target in ((site["current_link"], release), (site["web_link"], release / "frontend/dist")):
        link = Path(link)
        if link.exists() and not link.is_symlink():
            raise ValueError("发布入口已经存在且不是软链接")
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(target)
    shutil.copyfile(generated / "backend.service", f'/etc/systemd/system/{site["backend_service"]}.service')
    shutil.copyfile(generated / "nginx.conf", "/etc/nginx/sites-available/computing-platform")
    enabled = Path("/etc/nginx/sites-enabled/computing-platform")
    if not enabled.exists():
        enabled.symlink_to("/etc/nginx/sites-available/computing-platform")
    default = Path("/etc/nginx/sites-enabled/default")
    if default.is_symlink():
        default.unlink()
    Path("/etc/exports.d").mkdir(exist_ok=True)
    shutil.copyfile(generated / "nfs.exports", "/etc/exports.d/computing-platform.exports")
    run(["exportfs", "-ra"])
    run(["kubectl", "--kubeconfig", site["kubeconfig"], "apply", "-f", generated / "workspaces.yaml"])
    # Ubuntu nginx workers need writable spool directories for large uploads.
    shutil.copyfile(release / "deploy/nginx/platform-tmpfiles.conf", "/etc/tmpfiles.d/platform-nginx.conf")
    run(["systemd-tmpfiles", "--create", "/etc/tmpfiles.d/platform-nginx.conf"])
    run(["nginx", "-t"])
    run(["systemctl", "daemon-reload"])
    print("控制节点安装完成，后端未启动；确认数据库迁移、节点映射及镜像导入后按手册启动")


def install_agent(args, site):
    node = next((row for row in [site["control"], *site["workers"]] if row["name"] == args.node), None)
    if node is None:
        raise ValueError("未知节点")
    generated = Path(args.generated).resolve()
    if load_site(generated / "site.json") != site:
        raise ValueError("生成配置与站点不一致")
    monitor = read_env(generated / node["name"] / "monitor.env")
    if monitor["PLATFORM_MONITOR_TOKEN"].startswith("REPLACE"):
        raise ValueError("需提供与原节点 ID 对应的监控凭据")
    print("节点代理安装计划：监控服务；计算节点另配置 NFS 及镜像保存代理，保持服务停止")
    if not args.execute:
        return
    worker = node in site["workers"]
    if worker:
        values = read_env(generated / node["name"] / "agent.env")
        if len(values.get("WORKER_AGENT_TOKEN", "")) < 24:
            raise ValueError("镜像代理凭据缺失")
        if subprocess.run(["systemctl", "is-active", "platform-worker-agent"], capture_output=True).returncode == 0:
            raise ValueError("镜像代理仍在运行，请先结束保存任务并停止服务")
        Path(node["image_mount"]).mkdir(parents=True, exist_ok=True)
        line = (generated / node["name"] / "fstab").read_text()
        fstab = Path("/etc/fstab")
        old = fstab.read_text()
        existing = [row for row in old.splitlines() if row.strip() and not row.lstrip().startswith("#") and len(row.split()) > 1 and row.split()[1] == node["image_mount"]]
        if existing and existing != [line.strip()]:
            raise ValueError("NFS 挂载点已有不同配置，请先人工核对")
        if not existing:
            shutil.copyfile(fstab, "/etc/fstab.platform-before")
            write(fstab, old.rstrip() + "\n" + line, 0o644)
        run(["mount", node["image_mount"]]) if subprocess.run(["mountpoint", "-q", node["image_mount"]]).returncode else None
        Path("/opt/platform-worker-agent").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "deploy/worker-agent/worker_agent.py", "/opt/platform-worker-agent/worker_agent.py")
        shutil.copyfile(generated / node["name"] / "agent.env", "/etc/platform-worker-agent.env")
        Path("/etc/platform-worker-agent.env").chmod(0o600)
        shutil.copyfile(generated / node["name"] / "agent.service", "/etc/systemd/system/platform-worker-agent.service")
    Path("/opt/platform-monitor").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "scripts/monitor_agent.py", "/opt/platform-monitor/monitor_agent.py")
    shutil.copyfile(ROOT / "deploy/systemd/platform-monitor-agent.service", "/etc/systemd/system/platform-monitor-agent.service")
    shutil.copyfile(generated / node["name"] / "monitor.env", "/etc/platform-monitor.env")
    Path("/etc/platform-monitor.env").chmod(0o600)
    run(["systemctl", "daemon-reload"])
    print("代理安装完成，未启动；保留原数据库中的 token hash，无需生成新凭据")


def doctor(args, site):
    checks = []
    def record(name, ok):
        checks.append({"check": name, "ok": bool(ok)})
    with urllib.request.urlopen(site["public_url"].rstrip("/") + "/api/health", timeout=15) as response:
        health = json.load(response)
        record("API 与数据库就绪", health.get("status") == "healthy")
    with urllib.request.urlopen(site["public_url"].rstrip("/") + "/", timeout=15) as response:
        record("前端入口", b'<div id="app"' in response.read())
    cluster = json.loads(run(["kubectl", "--kubeconfig", site["kubeconfig"], "get", "nodes", "-o", "json"]))
    registered = {row["metadata"]["name"]: row for row in cluster["items"]}
    for node in [site["control"], *site["workers"]]:
        item = registered.get(node["name"], {})
        record(node["name"] + " Ready", any(c["type"] == "Ready" and c["status"] == "True" for c in item.get("status", {}).get("conditions", [])))
        if node in site["workers"]:
            record(node["name"] + " GPU 可分配", int(item.get("status", {}).get("allocatable", {}).get("nvidia.com/gpu", "0")) > 0)
    pvc = json.loads(run(["kubectl", "--kubeconfig", site["kubeconfig"], "get", "pvc", "platform-workspaces", "-n", site["namespace"], "-o", "json"]))
    record("共享 PVC Bound", pvc.get("status", {}).get("phase") == "Bound")
    if args.backend:
        state = backend_state(args.backend)
        record("数据库节点映射", {(row["id"], row["name"], row["ip"]) for row in state["nodes"]} == {(row["id"], row["name"], row["ip"]) for row in [site["control"], *site["workers"]]})
        for image in state["images"]:
            if image["snapshot_id"] and image["status"] == "ready":
                record(f'个人镜像 {image["id"]} 归档', (Path(site["image_store_root"]) / f'user_{image["owner_id"]}' / (image["snapshot_id"] + ".oci.tar")).is_file())
    print(json.dumps({"checks": checks, "usage_acceptance": "仍需按手册申请真实实例验证 Python、GPU、SSH、Jupyter、联网及释放复用"}, ensure_ascii=False, indent=2))
    if not all(row["ok"] for row in checks):
        raise ValueError("存在未通过检查")


def preflight(args, site):
    node = next((row for row in [site["control"], *site["workers"]] if row["name"] == args.node), None)
    if node is None:
        raise ValueError("preflight 需使用 --node 指定本机在站点中的名称")
    control = node["id"] == site["control"]["id"]
    programs = ["systemctl", "tar", "mount", "mountpoint", "python3", "k3s"]
    programs += [args.python, "mysql", "mysqldump", "nginx", "exportfs", "kubectl"] if control else ["nvidia-smi", "ctr", "crictl"]
    checks = [{"check": "命令 " + program, "ok": shutil.which(program) is not None} for program in programs]
    if control and shutil.which(args.python):
        version = run([args.python, "-c", "import sys;print('.'.join(map(str,sys.version_info[:2])))"]).decode().strip()
        checks.append({"check": "后端 Python 3.10", "ok": version == "3.10"})
    if not control and shutil.which("nvidia-smi"):
        checks.append({"check": "GPU 驱动", "ok": subprocess.run(["nvidia-smi", "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0})
    result = {"node": node["name"], "checks": checks,
              "note": "需另外核对新网段路由、DNS/NAT、时间同步、服务用户权限及镜像缓存"}
    if args.output:
        write(args.output, json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(row["ok"] for row in checks):
        raise ValueError("前置依赖检查未全部通过")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["render", "inventory", "rebind", "package", "backup", "restore", "verify", "export-images", "import-images", "install-control", "install-agent", "doctor", "preflight"])
    parser.add_argument("--site", default=str(ROOT / "deploy/migration/site.example.json"))
    parser.add_argument("--output")
    parser.add_argument("--backend")
    parser.add_argument("--backend-env")
    parser.add_argument("--monitor-tokens", help="本地 JSON，按原节点 ID 映射已有监控令牌")
    parser.add_argument("--bundle")
    parser.add_argument("--generated")
    parser.add_argument("--python", default="python3.10")
    parser.add_argument("--wheels")
    parser.add_argument("--extra-secrets", help="管理员自行收集的采集配置目录；不自动扫描 /etc")
    parser.add_argument("--secrets-output")
    parser.add_argument("--mysql-defaults")
    parser.add_argument("--mysql-host", default="localhost")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="root")
    parser.add_argument("--worker")
    parser.add_argument("--node")
    parser.add_argument("--inventory")
    parser.add_argument("--archive")
    parser.add_argument("--execute", action="store_true", help="显式执行备份、恢复、节点重绑或安装；不自动停止业务")
    args = parser.parse_args()
    required = {"render": ["output"], "inventory": ["backend", "output"], "rebind": ["backend"],
                "package": ["output"], "backup": ["backend", "output"], "restore": ["bundle", "secrets_output"],
                "verify": ["bundle"], "export-images": ["worker", "inventory", "output"],
                "import-images": ["worker", "inventory", "archive"], "install-control": ["bundle", "generated"], "install-agent": ["node", "generated"]}
    for name in required.get(args.command, []):
        if not getattr(args, name):
            parser.error("缺少 --" + name.replace("_", "-"))
    site = load_site(args.site)
    if args.command == "render":
        tokens = json.loads(Path(args.monitor_tokens).read_text()) if args.monitor_tokens else None
        render(site, args.output, args.backend_env, tokens)
        print("配置已生成，真实环境文件仅保存在指定本地目录；请核对数据库连接和代理凭据")
    elif args.command == "inventory":
        write(args.output, json.dumps(backend_state(args.backend), ensure_ascii=False, indent=2))
        print("只读盘点已保存；不包含账户密码或令牌")
    elif args.command == "rebind":
        if args.execute:
            stopped(site["backend_service"])
        print(json.dumps(backend_state(args.backend, "rebind", args.site, args.execute), ensure_ascii=False, indent=2))
    elif args.command == "package":
        package(args)
    elif args.command == "verify":
        manifest = verify(args.bundle)
        print(f'校验通过: {manifest["kind"]}, {len(manifest["files"])} 个文件')
    elif args.command in {"export-images", "import-images"}:
        node_images(args, site)
    else:
        {"backup": backup, "restore": restore, "install-control": install_control, "install-agent": install_agent, "doctor": doctor, "preflight": preflight}[args.command](args, site)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError) as error:
        print("操作停止: " + str(error), file=sys.stderr)
        sys.exit(1)
