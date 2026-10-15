import asyncio
import hashlib
import hmac
import logging
import math
import secrets
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.core.time import utc_iso, utc_naive
from app.models import Node, NodeMetric, GPU, NodeStatus, Allocation, AllocationStatus

logger = logging.getLogger(__name__)


class TelemetryService:
    @staticmethod
    def issue_token(db, node_id):
        node = db.query(Node).filter_by(id=node_id).with_for_update().first()
        if not node:
            raise ResourceNotFoundError("节点")
        value = secrets.token_urlsafe(36)
        node.monitor_token_hash = hashlib.sha256(value.encode()).hexdigest()
        return value

    @staticmethod
    def ingest(db, body, token):
        from fastapi import HTTPException
        node = db.query(Node).filter_by(hostname=body.node_name).with_for_update().first()
        digest = hashlib.sha256(token.encode()).hexdigest() if token else ""
        if node is None or not node.monitor_token_hash or not hmac.compare_digest(node.monitor_token_hash, digest):
            raise HTTPException(401, "采集凭据无效")
        now, collected = datetime.utcnow(), utc_naive(body.collected_at)
        if abs((now - collected).total_seconds()) > 120:
            raise ResourceConflictError("采集时间偏差超过2分钟，请同步主机时间")
        latest = TelemetryService.latest(db, node.id)
        if latest and collected <= utc_naive(latest.collected_at):
            return False
        registered = {gpu.gpu_index: gpu for gpu in db.query(GPU).filter_by(node_id=node.id)}
        seen, values = set(), []
        for gpu in body.gpus:
            if gpu.index in seen:
                raise ResourceConflictError("采样中存在重复 GPU")
            seen.add(gpu.index)
            record = registered.get(gpu.index)
            if record is None or (record.uuid and record.uuid != gpu.uuid):
                raise ResourceConflictError("采样 GPU 与登记设备不匹配")
            values.append({**gpu.model_dump(), "gpu_id": record.id})
        payload = body.model_dump(mode="json")
        payload["gpus"] = values
        payload["ownership_error"] = None
        if registered:
            if not body.device_mapping_available:
                payload["ownership_error"] = "设备分配记录暂不可读取"
            else:
                try:
                    owners, live_uids = TelemetryService.pod_owners(db, node, values)
                    for gpu in values:
                        current_uids = [uid for uid in gpu.get("pod_uids", []) if uid in live_uids]
                        assigned = {owners[uid] for uid in current_uids if uid in owners}
                        gpu["ownership_known"] = len(assigned) <= 1
                        gpu["allocation_id"] = next(iter(assigned)) if len(assigned) == 1 else None
                        gpu["external"] = (bool(current_uids) and any(uid not in owners for uid in current_uids)) or (
                            not assigned and ((gpu.get("memory_used_mb") or 0) > 0 or (gpu.get("utilization") or 0) > 0))
                        if gpu["external"]:
                            gpu["allocation_id"] = None
                except Exception:
                    payload["ownership_error"] = "实例与物理设备归属暂不可核对"
        if not registered:
            payload["gpu_error"] = None
        if len(values) != len(registered) and not payload["gpu_error"]:
            payload["gpu_error"] = "GPU 采集数量与登记数量不一致"
        node.last_heartbeat = now
        node.cpu_cores = body.cpu_cores
        node.memory_gb = body.memory_total_mb / 1024
        labels = dict(node.labels or {})
        if body.driver_version:
            labels["platform.driver_version"] = body.driver_version
        if body.driver_cuda_max:
            labels["platform.driver_cuda_max"] = body.driver_cuda_max
        node.labels = labels
        db.add(NodeMetric(node_id=node.id, collected_at=collected, received_at=now,
                          cpu_usage=body.cpu_usage, mem_usage=body.mem_usage, payload=payload))
        return True

    @staticmethod
    def pod_owners(db, node, values):
        if not any(gpu.get("pod_uids") for gpu in values):
            return {}, set()
        from app.infrastructure.kubernetes.client import create_clients
        core, network = create_clients()
        try:
            pods = core.list_pod_for_all_namespaces(field_selector="spec.nodeName=" + node.hostname,
                _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS).items
        finally:
            core.api_client.close()
            if network.api_client is not core.api_client:
                network.api_client.close()
        allocations = {row.pod_name: row for row in db.query(Allocation).filter(
            Allocation.node_id == node.id, Allocation.status != AllocationStatus.RELEASED).all()}
        owners, live_uids = {}, set()
        for pod in pods:
            if pod.status.phase in ("Succeeded", "Failed"):
                continue
            uid = pod.metadata.uid
            live_uids.add(uid)
            row = allocations.get(pod.metadata.name)
            labels = pod.metadata.labels or {}
            if row and labels.get("allocation-id") == str(row.id) and labels.get("user-id") == str(row.user_id):
                owners[uid] = row.id
        return owners, live_uids

    @staticmethod
    def latest(db, node_id):
        return db.query(NodeMetric).filter_by(node_id=node_id).order_by(NodeMetric.received_at.desc(), NodeMetric.id.desc()).first()

    @staticmethod
    def snapshot(db, node, *, now=None, detail=False):
        now = now or datetime.utcnow()
        sample = TelemetryService.latest(db, node.id)
        age = max(0, (now - utc_naive(sample.received_at)).total_seconds()) if sample else None
        fresh = sample is not None and age <= settings.TELEMETRY_STALE_SECONDS
        state = "missing" if sample is None else "stale" if not fresh else "live"
        payload = sample.payload if sample else {}
        if fresh and (sample.cpu_usage is None or sample.mem_usage is None or payload.get("gpu_error") or payload.get("ownership_error")):
            state = "partial"
        records = db.query(GPU).filter_by(node_id=node.id).order_by(GPU.gpu_index).all()
        metrics = {item["gpu_id"]: item for item in payload.get("gpus", [])} if fresh else {}
        gpu_list = []
        for gpu in records:
            measured = metrics.get(gpu.id, {})
            known = bool(measured.get("ownership_known")) and not payload.get("ownership_error")
            physical_status = "unknown" if not known else "external" if measured.get("external") else "occupied" if measured.get("allocation_id") else "free"
            if gpu.status.value == "maintenance":
                physical_status = "maintenance"
            gpu_list.append({"gpu_id": gpu.id, "index": gpu.gpu_index,
                "type": gpu.gpu_type.code if gpu.gpu_type else "unknown", "status": physical_status,
                "allocation_id": measured.get("allocation_id") if known else None,
                "utilization": measured.get("utilization"), "memory_used_mb": measured.get("memory_used_mb"),
                "memory_total_mb": measured.get("memory_total_mb"), "temperature": measured.get("temperature"),
                "power_watts": measured.get("power_watts")})
        can_schedule = node.status == NodeStatus.ONLINE and (not settings.TELEMETRY_ENFORCE_FRESHNESS or (
            fresh and not payload.get("gpu_error") and not payload.get("ownership_error") and len(metrics) == len(records)
            and not any(gpu.get("external") for gpu in metrics.values())))
        result = {"node_id": node.id, "name": node.hostname, "ip": node.ip,
            "gpus_total": len(records), "gpus_free": sum(gpu.status.value == "free" for gpu in records) if can_schedule else 0,
            "cpu_usage": sample.cpu_usage if fresh else None, "mem_usage": sample.mem_usage if fresh else None,
            "status": node.status.value, "telemetry_state": state, "schedulable": bool(can_schedule),
            "collected_at": utc_iso(sample.collected_at) if sample else None,
            "received_at": utc_iso(sample.received_at) if sample else None,
            "age_seconds": round(age, 1) if age is not None else None,
            "stale_after_seconds": settings.TELEMETRY_STALE_SECONDS,
            "gpu_error": payload.get("gpu_error") if fresh else None,
            "ownership_error": payload.get("ownership_error") if fresh else None,
            "cpu_cores": payload.get("cpu_cores") if fresh else None,
            "memory_total_mb": payload.get("memory_total_mb") if fresh else None,
            "memory_used_mb": payload.get("memory_used_mb") if fresh else None}
        if detail:
            result["gpu_list"] = gpu_list
        return result

    @staticmethod
    def eligible_node_ids(db):
        return [node.id for node in db.query(Node).all() if TelemetryService.snapshot(db, node)["schedulable"]]

    @staticmethod
    def history(db, node_id, minutes, *, now=None):
        if not db.get(Node, node_id):
            raise ResourceNotFoundError("节点")
        now = now or datetime.utcnow()
        start = now - timedelta(minutes=minutes)
        rows = db.query(NodeMetric).filter(NodeMetric.node_id == node_id,
            NodeMetric.received_at >= start, NodeMetric.received_at <= now).order_by(NodeMetric.received_at).all()
        step = max(15, math.ceil(minutes * 60 / 240))
        count = math.ceil(minutes * 60 / step)
        buckets = [[] for _ in range(count)]
        for row in rows:
            index = min(count - 1, int((utc_naive(row.received_at) - start).total_seconds() // step))
            buckets[index].append(row)
        def average(values):
            known = [value for value in values if value is not None]
            return round(sum(known) / len(known), 2) if known else None
        points = []
        for index, bucket in enumerate(buckets):
            gpus = {}
            for row in bucket:
                for gpu in row.payload.get("gpus", []):
                    gpus.setdefault(gpu["gpu_id"], []).append(gpu)
            points.append({"at": utc_iso(start + timedelta(seconds=index * step)),
                "cpu_usage": average([row.cpu_usage for row in bucket]),
                "mem_usage": average([row.mem_usage for row in bucket]),
                "samples": len(bucket), "gpus": [{"gpu_id": key,
                    "utilization": average([item.get("utilization") for item in values]),
                    "memory_used_mb": max((item["memory_used_mb"] for item in values if item.get("memory_used_mb") is not None), default=None),
                    "temperature": max((item["temperature"] for item in values if item.get("temperature") is not None), default=None),
                    "power_watts": average([item.get("power_watts") for item in values])} for key, values in gpus.items()]})
        return {"minutes": minutes, "bucket_seconds": step, "points": points}

    @staticmethod
    def prune(db):
        cutoff = datetime.utcnow() - timedelta(days=settings.TELEMETRY_RETENTION_DAYS)
        return db.query(NodeMetric).filter(NodeMetric.received_at < cutoff).delete(synchronize_session=False)


def cleanup_history():
    with SessionLocal() as db:
        TelemetryService.prune(db)
        db.commit()


async def telemetry_cleanup_loop(stop_event):
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(cleanup_history)
        except Exception:
            logger.exception("监控历史清理失败")
        try:
            await asyncio.wait_for(stop_event.wait(), 3600)
        except asyncio.TimeoutError:
            pass
