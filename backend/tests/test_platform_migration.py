import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models import Allocation, AllocationStatus, GPU, Image, ImageVisibility, Node
from scripts.migration_state import inventory, rebind

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("platform_ops", ROOT / "scripts/platform_ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


@pytest.fixture
def site(tmp_path):
    value = json.loads((ROOT / "deploy/migration/site.example.json").read_text())
    value.update(service_user="fixture_service", service_group="fixture_group")
    value["control"].update(ip="192.0.2.40", nfs_ip="192.0.2.40")
    value["workers"][0]["ip"] = "192.0.2.41"
    value["traefik_upstream"] = "http://192.0.2.41:31663"
    for key in ("release_root", "current_link", "web_link", "workspace_root", "image_store_root"):
        value[key] = str(tmp_path / key)
    return value


def add_schema(db):
    db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64))"))
    db.execute(text("INSERT INTO alembic_version VALUES ('0008_personal_image_history')"))
    db.commit()


def test_render_moves_all_network_and_storage_configuration(site, tmp_path):
    source = tmp_path / "source.env"
    source.write_text("DATABASE_URL=mysql+pymysql://fixture:unused@localhost/example\nSECRET_KEY=" + "x" * 40 + "\nWORKER_AGENT_TOKEN=" + "y" * 40)
    site["public_url"] = "http://new-campus.example.edu"
    site["workers"][0].update(ip="192.0.2.3", name="new-worker")
    site["control"]["ip"] = "192.0.2.4"
    site["control"]["nfs_ip"] = "192.0.2.4"
    site["traefik_upstream"] = "http://192.0.2.3:32000"
    output = ops.render(site, tmp_path / "rendered", source, {"1": "control-fixture", "2": "worker-fixture"})
    values = ops.read_env(output / "backend.env")
    assert values["DATABASE_URL"].endswith("/example")
    assert values["SECRET_KEY"] == "x" * 40
    assert values["CONTROL_NODE_ID"] == ""
    assert json.loads(values["WORKER_AGENT_URLS"]) == {"new-worker": "http://192.0.2.3:8091"}
    assert "new-campus.example.edu" in (output / "nginx.conf").read_text()
    assert "192.0.2.5" not in (output / "nginx.conf").read_text()
    assert site["workspace_root"] in (output / "workspaces.yaml").read_text()
    assert "192.0.2.4:" in (output / "new-worker/fstab").read_text()
    assert ops.read_env(output / "new-worker/monitor.env")["PLATFORM_MONITOR_TOKEN"] == "worker-fixture"
    with pytest.raises(ValueError, match="已存在"):
        ops.render(site, output, source)


@pytest.mark.parametrize("key,value", [("workspace_root", "/srv"), ("current_link", "/opt/../etc"),
                                       ("public_url", "http://host/extra"), ("service_user", "root;reboot")])
def test_site_rejects_unsafe_or_ambiguous_configuration(site, tmp_path, key, value):
    site[key] = value
    config = tmp_path / "site.json"
    config.write_text(json.dumps(site))
    with pytest.raises(ValueError):
        ops.load_site(config)


def test_backup_checksum_detects_corruption(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in ("database.sql.gz", "workspaces.tar.gz", "images.tar.gz", "backend.env", "inventory.json", "site.json"):
        (bundle / name).write_bytes(b"fixture")
    ops.seal(bundle, "backup")
    assert ops.verify(bundle)["kind"] == "backup"
    (bundle / "images.tar.gz").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="校验失败"):
        ops.verify(bundle)


@pytest.mark.parametrize("kind", ["path", "symlink"])
@pytest.mark.parametrize("legacy", [False, True])
def test_archive_cannot_write_outside_target(tmp_path, kind, legacy, monkeypatch):
    if legacy:
        monkeypatch.delattr(tarfile, "data_filter")
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo("../escaped" if kind == "path" else "escape-link")
        if kind == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "../../escaped"
        output.addfile(member)
    with pytest.raises((ValueError, tarfile.TarError)):
        ops.extract(archive, tmp_path / "target")
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_archive_preserves_hidden_secret_and_shared_directory_mode(tmp_path, legacy, monkeypatch):
    if legacy:
        monkeypatch.delattr(tarfile, "data_filter")
    source = tmp_path / "source"
    source.mkdir(mode=0o2770)
    source.chmod(0o2770)
    (source / ".platform-secret").write_text("fixture-secret")
    (source / ".platform-secret").chmod(0o600)
    archive = tmp_path / "storage.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname=".")
    target = tmp_path / "restored"
    ops.extract(archive, target)
    assert (target / ".platform-secret").read_text() == "fixture-secret"
    assert target.stat().st_mode & 0o2770 == 0o2770
    assert (target / ".platform-secret").stat().st_mode & 0o777 == 0o600


def test_public_export_normalizes_aliases_and_ignores_retired_entries(site, tmp_path, capsys):
    state = {"images": [
        {"ref": "jupyter-test:latest", "visibility": "public", "status": "ready", "snapshot_id": None},
        {"ref": "docker.io/library/jupyter-test:latest", "visibility": "public", "status": "ready", "snapshot_id": None},
        {"ref": "pytorch/pytorch:latest", "visibility": "public", "status": "retired", "snapshot_id": None}]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(state))
    ops.node_images(SimpleNamespace(command="export-images", worker="worker1", inventory=path, execute=False), site)
    printed = capsys.readouterr().out
    assert printed.count("docker.io/library/jupyter-test:latest") == 1
    assert "pytorch" not in printed


def test_oci_validation_rejects_missing_referenced_layers(tmp_path):
    archive = tmp_path / "incomplete-oci.tar"
    with tarfile.open(archive, "w") as output:
        for name, data in {"oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
                           "index.json": json.dumps({"manifests": [{"digest": "sha256:" + "a" * 64, "size": 10}]}).encode()}.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="缺少引用内容"):
        ops.validate_oci(archive)


def test_backup_refuses_live_service_before_creating_output(site, tmp_path, monkeypatch):
    for key in ("workspace_root", "image_store_root"):
        Path(site[key]).mkdir()
    monkeypatch.setattr(ops, "backend_state", lambda _: {"database_name": site["database_name"], "unfinished": {"allocations": 0}})
    monkeypatch.setattr(ops, "stopped", lambda _: (_ for _ in ()).throw(ValueError("后端服务尚未停止")))
    args = SimpleNamespace(backend=tmp_path, output=tmp_path / "backup", execute=True)
    with pytest.raises(ValueError, match="尚未停止"):
        ops.backup(args, site)
    assert not Path(args.output).exists()


def test_restore_refuses_nonempty_storage_before_database_access(site, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "site.json").write_text(json.dumps(site))
    monkeypatch.setattr(ops, "verify", lambda *_: {"files": {}})
    target = Path(site["workspace_root"])
    target.mkdir()
    (target / "keep.txt").write_text("existing data")
    args = SimpleNamespace(bundle=bundle, secrets_output=tmp_path / "secrets", execute=True)
    with pytest.raises(ValueError, match="空目录"):
        ops.restore(args, site)
    assert (target / "keep.txt").read_text() == "existing data"


def test_rebinding_preserves_ids_hardware_and_personal_image_history(db):
    add_schema(db)
    db.add(Node(id=2, hostname="control-old", ip="10.0.0.1"))
    db.add(Image(id=3, name="platform.local/user-1/test", tag="v1", owner_id=1,
                 visibility=ImageVisibility.PRIVATE, snapshot_id="a" * 32, source_node_id=1))
    row = Allocation(request_id="migration-history", user_id=1, node_id=1, pool_id=1,
                     image_id=3, requested_gpu_count=1, gpu_type_id=1, status=AllocationStatus.RELEASED)
    db.add(row)
    db.get(GPU, 1).uuid = "GPU-original-device"
    db.commit()
    site = {"control": {"id": 2, "name": "new-control", "ip": "10.20.0.1"},
            "workers": [{"id": 1, "name": "new-worker", "ip": "10.20.0.2"}]}
    assert not any(inventory(db)["unfinished"].values())
    assert rebind(db, site)["applied"] is False
    assert db.get(Node, 1).hostname == "worker-a"
    rebind(db, site, apply=True)
    assert db.get(Node, 1).hostname == "new-worker"
    assert row.node_id == db.get(Image, 3).source_node_id == 1
    assert db.get(GPU, 1).uuid == "GPU-original-device"
    assert db.get(Allocation, row.id).image_id == 3


def test_rebinding_blocks_inflight_resources_and_incomplete_node_maps(db):
    add_schema(db)
    site = {"control": {"id": 1, "name": "new", "ip": "10.20.0.1"}, "workers": []}
    db.get(GPU, 1).status = "reserved"
    db.commit()
    with pytest.raises(ValueError, match="未结束"):
        rebind(db, site, apply=True)
    db.get(GPU, 1).status = "free"
    db.commit()
    site["control"]["id"] = 99
    with pytest.raises(ValueError, match="已有节点 ID"):
        rebind(db, site, apply=True)
    assert db.get(Node, 1).hostname == "worker-a"
