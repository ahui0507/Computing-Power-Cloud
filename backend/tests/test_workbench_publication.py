import pytest

from app.core.exceptions import AuthorizationError, ResourceConflictError
from app.models import AuditLog, Image, ImageVisibility, User
from app.services.image_service import ImageService
from scripts.publish_workbench import register


def test_stage_verify_publish_and_repeat_preserve_personal_images(db):
    db.get(User, 2).role_id = 1
    db.commit()
    db.expire_all()
    preview = register(db, 2, 3 * 1024**3, staging_owner_id=1)
    assert preview["image_id"] is None
    staged = register(db, 2, 3 * 1024**3, staging_owner_id=1, apply=True)
    image = db.get(Image, staged["image_id"])
    assert image.visibility == ImageVisibility.PRIVATE and image.owner_id == 1
    assert image not in ImageService.get_public_images(db)
    published = register(db, 2, 3 * 1024**3, apply=True)
    assert published["image_id"] == image.id and image.owner_id is None and image.supports_ssh
    assert ImageService.get_public_images(db)[0].id == image.id
    assert register(db, 2, 3 * 1024**3, apply=True)["changed"] is False
    assert db.query(AuditLog).count() == 2
    assert db.get(Image, 2).visibility == ImageVisibility.PRIVATE
    with pytest.raises(ResourceConflictError):
        register(db, 2, 3 * 1024**3, staging_owner_id=1, apply=True)


def test_regular_user_cannot_publish_workbench(db):
    with pytest.raises(AuthorizationError):
        register(db, 1, 3 * 1024**3, apply=True)
    assert db.query(Image).count() == 2


def test_public_environment_order_prefers_new_complete_environment(db):
    db.add_all([Image(id=3, name="complete-old", tag="old", supports_ssh=True),
                Image(id=4, name="complete-new", tag="new", supports_ssh=True),
                Image(id=5, name="test-new", tag="new", supports_ssh=False),
                Image(id=6, name="retired", tag="new", supports_ssh=True, snapshot_status="retired")])
    db.commit()
    assert [image.id for image in ImageService.get_public_images(db)] == [4, 3, 5, 1]
