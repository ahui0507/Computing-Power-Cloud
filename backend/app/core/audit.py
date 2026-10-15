"""Shared audit recording, independent of HTTP routers."""

from app.models.audit import AuditLog


def audit(db, user, action, resource_type, resource_id, *, detail=None):
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            detail=detail,
            result="success",
        )
    )
