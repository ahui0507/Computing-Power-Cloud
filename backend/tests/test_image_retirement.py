from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import AuthorizationError
from app.models import Allocation, AllocationStatus, AuditLog, GPU, GPUStatus, Image, ImageVisibility, Instance, InstanceStatus, User
from scripts.retire_unusable_images import retire_public_images


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def prepare(db):
    db.get(User, 2).role_id = 1
    db.add_all([
        Image(id=3, name="pytorch/pytorch", tag="latest", visibility=ImageVisibility.PUBLIC),
        Image(id=4, name="pytorch/pytorch", tag="latest", visibility=ImageVisibility.PRIVATE, owner_id=1),
        Image(id=5, name="docker.io/library/campus-workbench", tag="20261012", visibility=ImageVisibility.PUBLIC),
    ])
    db.commit()
    db.expire_all()


def test_retirement_preview_and_repeat_preserve_private_images(client, db):
    prepare(db)
    assert [item["image_id"] for item in retire_public_images(db, 2)] == [3]
    assert db.get(Image, 3).snapshot_status == "ready"
    assert db.query(AuditLog).count() == 0
    assert [item["image_id"] for item in retire_public_images(db, 2, apply=True)] == [3]
    assert retire_public_images(db, 2, apply=True) == []
    assert db.query(AuditLog).count() == 1
    assert db.get(Image, 4).snapshot_status == "ready"
    assert db.get(Image, 5).snapshot_status == "ready"
    assert {item["image_id"] for item in client.get("/images/public").json()["data"]} == {1, 5}
    assert any(item["image_id"] == 4 for item in client.get("/images/my").json()["data"])


def test_retired_image_rejects_new_requests_and_preserves_history(client, db):
    prepare(db)
    allocation = Allocation(request_id=uuid4().hex, user_id=1, node_id=1, pool_id=1,
        image_id=3, image_name="pytorch/pytorch:latest", requested_gpu_count=1, gpu_type_id=1,
        status=AllocationStatus.RELEASED, container_id="historical-image", start_time=datetime.utcnow())
    db.add(allocation); db.flush()
    instance = Instance(allocation_id=allocation.id, instance_name=allocation.container_id,
        node_id=1, gpu_ids=[1], image_id=3, status=InstanceStatus.STOPPED)
    db.add(instance); db.commit()
    retire_public_images(db, 2, apply=True)
    result = client.post("/resource/apply", json={"pool_id":1,"gpu_count":1,"image_id":3})
    assert result.status_code == 409 and "已下架" in result.json()["message"]
    db.refresh(allocation); db.refresh(instance)
    assert allocation.image_id == instance.image_id == 3
    assert allocation.status == AllocationStatus.RELEASED
    assert db.query(GPU).filter_by(status=GPUStatus.FREE).count() == 2
    assert db.query(Allocation).count() == 1


def test_only_administrator_can_retire_images(db):
    prepare(db)
    with pytest.raises(AuthorizationError):
        retire_public_images(db, 1, apply=True)
    assert db.get(Image, 3).snapshot_status == "ready"


@pytest.mark.parametrize("name,tag", [
    ("campus-workbench", "20261010"),
    ("docker.io/library/campus-workbench", "20261011"),
    ("jupyter-test", "latest"),
    ("docker.io/library/jupyter-test", "latest"),
])
def test_legacy_public_environment_retirement_preserves_personal_copy(db, name, tag):
    prepare(db)
    db.add_all([
        Image(id=6, name=name, tag=tag, visibility=ImageVisibility.PUBLIC),
        Image(id=7, name=name, tag=tag, visibility=ImageVisibility.PRIVATE, owner_id=1),
    ])
    db.commit()
    assert 6 in {item["image_id"] for item in retire_public_images(db, 2, apply=True)}
    assert db.get(Image, 6).snapshot_status == "retired"
    assert db.get(Image, 7).snapshot_status == "ready"
    assert db.get(Image, 5).snapshot_status == "ready"
