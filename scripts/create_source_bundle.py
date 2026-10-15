"""Export source from an explicit allowlist; never include local credentials or runtime data."""
from pathlib import Path
import argparse, tarfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'backend', 'frontend', 'database', 'deploy', 'scripts', 'examples', 'test-images', 'docs'}
SKIP_DIRS = {'.git', '.ops', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', '.ruff_cache', 'dist', 'build', 'storage', 'data', 'backups', 'validation'}
SKIP_NAMES = {'账号密码.txt', '本地凭据.txt', 'credentials.json', 'secrets.yaml', 'secrets.json', 'site.local.json', 'config.local.json'}


def permitted(path):
    relative = path.relative_to(ROOT)
    if relative.parts[0] not in DIRECTORIES and relative.as_posix() not in {'README.md', 'API.yaml', '.gitignore', '.dockerignore', '.gitattributes'}:
        return False
    if any(part in SKIP_DIRS for part in relative.parts) or path.name in SKIP_NAMES or path.is_symlink():
        return False
    if 'kubeconfig' in path.name.lower() or path.suffix in {'.key', '.pem', '.db', '.sqlite', '.log', '.pyc', '.tar', '.gz', '.zip'}:
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if path.suffix == '.env' or ('secrets' in path.name.lower() and not path.name.endswith('.example')):
        return False
    return True


def bundle(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new filename')
    files = []
    for directory in sorted(DIRECTORIES):
        base = ROOT / directory
        if not base.exists(): continue
        import os
        for parent,dirs,names in os.walk(base):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            files.extend(Path(parent)/name for name in names if permitted(Path(parent)/name))
    files.extend(ROOT/name for name in ['README.md','API.yaml','.gitignore','.dockerignore','.gitattributes'] if (ROOT/name).is_file())
    output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        def source_metadata(info):
            info.mode = 0o755 if info.isdir() else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            return info
        for path in sorted(set(files)):
            archive.add(path,arcname=path.relative_to(ROOT).as_posix(),recursive=False,filter=source_metadata)
    return len(set(files))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('output')
    print('Source files exported:', bundle(parser.parse_args().output))
