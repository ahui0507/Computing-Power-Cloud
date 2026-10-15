"""数据库以 UTC 无时区时间保存，对外明确返回 UTC 偏移。"""
from datetime import datetime, timezone


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_iso(value: datetime):
    if value is None:
        return None
    return utc_naive(value).replace(tzinfo=timezone.utc).isoformat()
