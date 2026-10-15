from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User, BalanceCredit, Payment, AuditLog


@pytest.fixture
def client(db):
    admin = db.get(User, 1)
    admin.role_id = 1
    db.commit()
    db.expire_all()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def payload(**values):
    return {"request_id": str(uuid4()), "amount": "12.3456", "reason": "项目额度", **values}


def test_credit_persists_balance_payment_audit_and_is_visible_only_to_owner(client, db):
    response = client.post("/admin/users/2/balance-credits", json=payload(reason=" 项目额度 "))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["balance_before"] == 100 and data["balance_after"] == 112.3456
    assert data["reason"] == "项目额度"
    assert db.get(User, 2).balance == Decimal("112.3456")
    assert db.query(Payment).one().amount == Decimal("12.3456")
    audit = db.query(AuditLog).one()
    assert audit.user_id == 1 and audit.resource_id == "2"
    assert audit.detail["amount"] == "12.3456" and audit.detail["reason"] == "项目额度"
    assert client.get("/admin/users/2/balance-credits").json()["data"]["total"] == 1
    assert client.get("/billing/credits").json()["data"]["total"] == 0
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.get("/billing/credits").json()["data"]["items"][0]["id"] == data["id"]
    assert client.get("/billing/credits", params={"user_id": 1}).json()["data"]["total"] == 1
    assert client.post("/admin/users/2/balance-credits", json=payload()).status_code == 403
    assert client.get("/admin/users/2/balance-credits").status_code == 403


def test_retry_returns_one_receipt_even_after_later_balance_changes(client, db):
    body = payload()
    first = client.post("/admin/users/2/balance-credits", json=body).json()["data"]
    # 模拟此后实例结算；旧请求重试不能再次增加，也不能返回另一笔操作的余额。
    db.get(User, 2).balance = Decimal("110")
    db.commit()
    repeat = client.post("/admin/users/2/balance-credits", json=body)
    assert repeat.status_code == 200 and repeat.json()["data"] == first
    assert db.get(User, 2).balance == Decimal("110")
    assert db.query(Payment).count() == db.query(BalanceCredit).count() == db.query(AuditLog).count() == 1
    assert client.post("/admin/users/2/balance-credits", json={**body, "amount": "1"}).status_code == 409
    assert client.post("/admin/users/2/balance-credits", json={**body, "reason": "其他用途"}).status_code == 409


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "0.00001", "1000000.0001"])
def test_invalid_amount_does_not_change_balance(client, db, amount):
    assert client.post("/admin/users/2/balance-credits", json=payload(amount=amount)).status_code == 422
    assert db.get(User, 2).balance == 100
    assert db.query(Payment).count() == db.query(BalanceCredit).count() == db.query(AuditLog).count() == 0


@pytest.mark.parametrize("reason", ["", "   ", "a" * 201])
def test_reason_required(client, reason):
    assert client.post("/admin/users/2/balance-credits", json=payload(reason=reason)).status_code == 422


def test_missing_deleted_admin_targets_and_balance_overflow_rejected(client, db):
    assert client.post("/admin/users/999/balance-credits", json=payload()).status_code == 404
    assert client.post("/admin/users/1/balance-credits", json=payload()).status_code == 409
    user = db.get(User, 2)
    user.deleted_at = datetime.utcnow()
    db.commit()
    assert client.post("/admin/users/2/balance-credits", json=payload()).status_code == 404
    user.deleted_at = None
    user.balance = Decimal("99999999.9999")
    db.commit()
    assert client.post("/admin/users/2/balance-credits", json=payload()).status_code == 409
    assert db.query(Payment).count() == 0


def test_failed_transaction_rolls_back_balance_payment_and_audit(client, db):
    def fail(mapper, connection, target):
        raise RuntimeError("simulated audit persistence failure")

    event.listen(AuditLog, "before_insert", fail)
    try:
        assert client.post("/admin/users/2/balance-credits", json=payload()).status_code == 500
    finally:
        event.remove(AuditLog, "before_insert", fail)
        db.rollback()
    assert db.get(User, 2).balance == 100
    assert db.query(Payment).count() == db.query(BalanceCredit).count() == db.query(AuditLog).count() == 0


def test_history_pagination_and_negative_balance_credit(client, db):
    db.get(User, 2).balance = Decimal("-5")
    db.commit()
    for _ in range(2):
        assert client.post("/admin/users/2/balance-credits", json=payload(amount="0.0001")).status_code == 200
    assert db.get(User, 2).balance == Decimal("-4.9998")
    first = client.get("/admin/users/2/balance-credits?page_size=1").json()["data"]
    second = client.get("/admin/users/2/balance-credits?page_size=1&page=2").json()["data"]
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] > second["items"][0]["id"]
