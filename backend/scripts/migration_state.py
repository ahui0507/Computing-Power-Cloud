"""迁移前只读盘点；停机后按原节点 ID 调整地址，保留历史外键。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.models import Allocation, AllocationOperation, GPU, Image, Instance, Node


def inventory(db):
    unfinished = {
        "allocations": db.query(Allocation).filter(Allocation.status.in_(["pending", "approved", "active", "releasing"])).count(),
        "operations": db.query(AllocationOperation).filter(AllocationOperation.status.in_(["pending", "running"])).count(),
        "images": db.query(Image).filter(Image.snapshot_status.in_(["saving", "deleting"])).count(),
        "gpus": db.query(GPU).filter(GPU.status.in_(["reserved", "occupied"])).count(),
        "instances": db.query(Instance).filter(Instance.status.in_(["creating", "running"])).count(),
    }
    return {"format": 1, "schema": db.execute(text("SELECT version_num FROM alembic_version")).scalar(),
            "database_name": db.bind.url.database,
            "database_server_uuid": db.execute(text("SELECT @@server_uuid")).scalar() if db.bind.dialect.name == "mysql" else None,
            "unfinished": unfinished,
            "nodes": [{"id": row.id, "name": row.hostname, "ip": row.ip, "gpu_count": row.gpus_total}
                      for row in db.query(Node).order_by(Node.id)],
            "images": [{"id": row.id, "ref": f"{row.name}:{row.tag}", "visibility": row.visibility.value,
                        "status": row.snapshot_status, "owner_id": row.owner_id,
                        "snapshot_id": row.snapshot_id, "source_node_id": row.source_node_id}
                       for row in db.query(Image).order_by(Image.id)]}


def rebind(db, site, apply=False):
    state = inventory(db)
    if any(state["unfinished"].values()):
        raise ValueError("仍有未结束实例、资源操作、镜像任务或 GPU 预留，不能调整节点")
    targets = [site["control"], *site["workers"]]
    ids = {row["id"] for row in targets}
    current = {row.id: row for row in db.query(Node).all()}
    if ids != set(current):
        raise ValueError("迁移配置必须逐一列出已有节点 ID；增删硬件应另行登记")
    changes = []
    for target in targets:
        node = current[target["id"]]
        changes.append({"id": node.id, "old_name": node.hostname, "new_name": target["name"],
                        "old_ip": node.ip, "new_ip": target["ip"]})
    if len({row["new_name"] for row in changes}) != len(changes):
        raise ValueError("目标节点名重复")
    # 临时名称允许两个既有节点交换主机名，而不触发唯一约束。
    if apply:
        for node in current.values():
            node.hostname = f"migration-temporary-{node.id}"
        db.flush()
        for target in targets:
            node = current[target["id"]]
            node.hostname, node.ip = target["name"], target["ip"]
            node.last_heartbeat = None
        db.commit()
    return {"applied": apply, "changes": changes,
            "preserved": "节点、GPU、资源池及个人镜像的原 ID 和历史外键保持不变；硬件 UUID 未改写"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "rebind"])
    parser.add_argument("--site")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = inventory(db) if args.command == "inventory" else rebind(db, json.loads(Path(args.site).read_text(encoding="utf-8-sig")), args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
