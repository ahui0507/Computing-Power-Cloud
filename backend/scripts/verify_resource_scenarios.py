"""真实集群资源验收：复用、多卡、独立并发申请和多用户争抢剩余名额。

标准输入为 [{"email": ..., "password": ...}, ...]，至少 8 个独立普通用户。
需要完整仓库、现场数据库和 kubeconfig。会创建 GPU 实例并产生内部账单，
仅清理本次创建的实例和测试文件，报告不保存密码、JWT 或 Jupyter 令牌。
"""
import argparse
import concurrent.futures
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.core.database import SessionLocal
from app.infrastructure.kubernetes.client import create_clients
from app.models import Allocation, BillingRecord, GPU, Node, ResourcePool, User


class CheckFailed(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


@dataclass
class Account:
    user_id: int
    client: httpx.Client


class ResourceScenarios:
    def __init__(self, args, credentials):
        self.args = args
        self.accounts = []
        self.tracked = {}
        self.request_ids = set()
        self.guard = threading.Lock()
        self.run_id = uuid.uuid4().hex[:12]
        self.core, self.network = create_clients()
        self.report = {
            "passed": False,
            "rounds": args.rounds,
            "cases": [],
            "cleanup_errors": [],
        }
        self.secrets = [item["password"] for item in credentials]
        for item in credentials:
            client = httpx.Client(base_url=args.api_url.rstrip("/"), timeout=120)
            response = client.post("/auth/login", json=item)
            require(response.status_code == 200, "Test account login failed")
            client.headers["Authorization"] = (
                "Bearer " + response.json()["data"]["token"]
            )
            info = client.get("/auth/user_info").json()["data"]
            require(info["role"] == "user", "Use ordinary users for these scenarios")
            self.accounts.append(Account(info["user_id"], client))
        require(
            len({a.user_id for a in self.accounts}) >= 8,
            "Eight distinct users are required",
        )
        with SessionLocal() as db:
            pool = db.get(ResourcePool, args.pool_id)
            require(pool is not None, "Resource pool does not exist")
            self.node_ids, self.gpu_type_id = list(pool.node_ids), pool.gpu_type_id
            self.capacity = (
                db.query(GPU)
                .filter(
                    GPU.node_id.in_(self.node_ids), GPU.gpu_type_id == self.gpu_type_id
                )
                .count()
            )
            self.initial_balances = {
                a.user_id: db.get(User, a.user_id).balance for a in self.accounts
            }
        require(self.capacity == 4, "This suite requires the four-GPU acceptance pool")
        self.state(4)

    def emit(self, **event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def key(self, label):
        return f"scenario-{self.run_id}-{label}-{uuid.uuid4().hex[:10]}"

    def apply(self, account, count=1, key=None):
        key = key or self.key("apply")
        with self.guard:
            self.request_ids.add(
                hashlib.sha256(f"{account.user_id}:{key}".encode()).hexdigest()
            )
        response = account.client.post(
            "/resource/apply",
            headers={"Idempotency-Key": key},
            json={
                "pool_id": self.args.pool_id,
                "image_id": self.args.image_id,
                "gpu_count": count,
            },
        )
        result = {"http_status": response.status_code, "user_id": account.user_id}
        if response.status_code == 200:
            container = response.json()["data"]["container_id"]
            result["container_id"] = container
            with self.guard:
                self.tracked[container] = account
        return result

    def accepted(self, account, count=1):
        result = self.apply(account, count)
        require(
            result["http_status"] == 200,
            f"Application returned {result['http_status']}",
        )
        return result["container_id"]

    def batch(self, jobs):
        barrier = threading.Barrier(len(jobs))

        def execute(job):
            barrier.wait(timeout=10)
            try:
                return job()
            except Exception as exc:
                return {"http_status": 0, "failure": type(exc).__name__}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            return list(executor.map(execute, jobs))

    def wait(self, containers, status="running"):
        pending = set(containers)
        deadline = time.monotonic() + self.args.startup_timeout
        while pending:
            for account in {
                self.tracked[c].user_id: self.tracked[c] for c in pending
            }.values():
                response = account.client.get("/resource/my")
                require(response.status_code == 200, "Instance list failed")
                for row in response.json()["data"]:
                    if row["container_id"] not in pending:
                        continue
                    require(
                        row["status"] != "failed", "Test instance entered failed state"
                    )
                    if row["status"] == status:
                        pending.remove(row["container_id"])
            require(time.monotonic() < deadline, f"Timed out waiting for {status}")
            if pending:
                time.sleep(1)

    def state(self, expected_free):
        with SessionLocal() as db:
            gpus = (
                db.query(GPU)
                .filter(
                    GPU.node_id.in_(self.node_ids), GPU.gpu_type_id == self.gpu_type_id
                )
                .all()
            )
            free = sum(
                g.status.value == "free" and g.allocation_id is None for g in gpus
            )
            node_free = sum(db.get(Node, n).gpus_free for n in self.node_ids)
            pool_free = db.get(ResourcePool, self.args.pool_id).free_gpus
            occupied = [g for g in gpus if g.allocation_id is not None]
            for gpu in occupied:
                owner = db.get(Allocation, gpu.allocation_id)
                require(
                    gpu.id in owner.gpu_ids and gpu.occupied_by == owner.user_id,
                    "GPU reservation and allocation ownership disagree",
                )
        pools = self.accounts[0].client.get("/resource/pools").json()["data"]
        api_free = next(
            p["free_gpus"] for p in pools if p["pool_id"] == self.args.pool_id
        )
        actual = {
            "database_free": free,
            "api_free": api_free,
            "node_cache_free": node_free,
            "pool_cache_free": pool_free,
        }
        require(
            all(v == expected_free for v in actual.values()),
            f"Free GPU count mismatch: expected {expected_free}, got {actual}",
        )
        return actual

    def exec_stdout(self, pod_name, command):
        channel = stream(
            self.core.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=settings.K8S_NAMESPACE,
            command=command,
            stdout=True,
            stderr=True,
            stdin=False,
            tty=False,
            _preload_content=False,
            _request_timeout=30,
        )
        try:
            channel.run_forever(timeout=45)
            require(not channel.is_open(), "Container command timed out")
            output = channel.read_stdout()
            require(channel.returncode == 0, "GPU verification command failed")
            return output
        finally:
            channel.close()

    def workload(self, container, count, compute=True):
        allocation_id = int(container.split("-")[1])
        pods = self.core.list_namespaced_pod(
            settings.K8S_NAMESPACE, label_selector=f"allocation-id={allocation_id}"
        ).items
        require(len(pods) == 1, "Application did not create exactly one Pod")
        pod = pods[0]
        require(
            pod.metadata.labels["user-id"] == str(self.tracked[container].user_id),
            "Pod has the wrong owner",
        )
        require(
            int(pod.spec.containers[0].resources.limits["nvidia.com/gpu"]) == count,
            "Pod GPU limit differs from the request",
        )
        devices = (
            self.exec_stdout(
                pod.metadata.name,
                ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            )
            .strip()
            .splitlines()
        )
        require(
            len(devices) == count and len(set(devices)) == count,
            "Container sees the wrong number of physical GPUs",
        )
        if compute:
            source = (
                Path(__file__).resolve().parents[2]
                / "test-images/jupyter-test/gpu_check.py"
            ).read_text()
            code = (
                "import json\nns={'__name__':'scenario_gpu_check'}\n"
                + f"exec(compile({source!r}, 'gpu_check.py', 'exec'), ns)\n"
                + f"print(json.dumps([ns['run'](i) for i in range({count})]))"
            )
            results = json.loads(
                self.exec_stdout(pod.metadata.name, ["python", "-c", code])
            )
            require(
                len(results) == count
                and all(r == {"visible_gpus": count, "computed": 42} for r in results),
                "CUDA computation failed on a requested GPU",
            )
        return devices

    def disjoint_workloads(self, requests):
        seen = set()
        result = []
        for container, count in requests:
            devices = self.workload(container, count)
            require(
                not seen.intersection(devices),
                "Two instances received the same physical GPU",
            )
            seen.update(devices)
            result.append(
                {"container_id": container, "gpu_count": count, "gpu_uuids": devices}
            )
        return result

    def release(self, container):
        response = self.tracked[container].client.post(
            "/resource/release", json={"container_id": container}
        )
        require(response.status_code == 200, f"Release returned {response.status_code}")
        return {"http_status": response.status_code}

    def released(self, containers):
        self.wait(containers, "released")
        with SessionLocal() as db:
            for container in containers:
                allocation = (
                    db.query(Allocation).filter_by(container_id=container).one()
                )
                require(
                    db.query(GPU).filter_by(allocation_id=allocation.id).count() == 0,
                    "Released application still owns a logical GPU",
                )
                rows = (
                    db.query(BillingRecord).filter_by(allocation_id=allocation.id).all()
                )
                require(len(rows) == 1, "Release did not settle exactly once")
                record = rows[0]
                seconds = Decimal(
                    str((record.end_time - record.start_time).total_seconds())
                )
                expected = (
                    allocation.hourly_price
                    * allocation.requested_gpu_count
                    * seconds
                    / Decimal(3600)
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                require(
                    record.amount == expected and record.amount > 0,
                    "Billing amount does not match GPU count and actual runtime",
                )
                for read, name in (
                    (self.core.read_namespaced_pod, allocation.pod_name),
                    (self.core.read_namespaced_service, f"svc-{allocation.id}"),
                    (self.network.read_namespaced_ingress, f"jupyter-{allocation.id}"),
                    (self.core.read_namespaced_secret, f"jupyter-auth-{allocation.id}"),
                ):
                    try:
                        read(name, settings.K8S_NAMESPACE, _request_timeout=10)
                    except ApiException as exc:
                        require(exc.status == 404, "Could not verify cluster cleanup")
                    else:
                        raise CheckFailed(
                            "Released instance left a cluster object behind"
                        )

    def release_many(self, containers):
        results = self.batch([lambda c=c: self.release(c) for c in containers])
        require(
            all(r["http_status"] == 200 for r in results),
            f"Concurrent release failed: {results}",
        )
        self.released(containers)

    def assert_denied(self, account, count):
        with SessionLocal() as db:
            before = db.query(Allocation).filter_by(user_id=account.user_id).count()
            balance = db.get(User, account.user_id).balance
        result = self.apply(account, count)
        require(
            result["http_status"] in (400, 409), f"Capacity rejection failed: {result}"
        )
        with SessionLocal() as db:
            require(
                db.query(Allocation).filter_by(user_id=account.user_id).count()
                == before,
                "Rejected request left an allocation behind",
            )
            require(
                db.get(User, account.user_id).balance == balance,
                "Rejected request charged the user",
            )

    def release_reapply(self):
        user = self.accounts[0]
        filename = f"resource-scenarios-{self.run_id}.txt"
        content = b"persist-across-resource-release"
        response = user.client.post(
            "/storage/upload", files={"file": (filename, content)}
        )
        require(response.status_code == 200, "File upload failed")
        containers = []
        try:
            for _ in range(self.args.rounds):
                container = self.accepted(user)
                require(
                    container not in containers,
                    "New application reused a released instance ID",
                )
                self.wait([container])
                self.state(3)
                self.workload(container, 1)
                if containers:
                    # 重试旧实例的释放，不能回收已经重新分配给新实例的 GPU。
                    self.release(containers[-1])
                    self.released([containers[-1]])
                    self.state(3)
                row = next(
                    r
                    for r in user.client.get("/resource/my").json()["data"]
                    if r["container_id"] == container
                )
                url = urlsplit(row["jupyter_url"])
                token = parse_qs(url.query)["token"][0]
                endpoint = urlunsplit(
                    (
                        url.scheme,
                        url.netloc,
                        url.path.rstrip("/") + "/api/contents/" + filename,
                        "",
                        "",
                    )
                )
                saved = user.client.get(
                    endpoint,
                    headers={"Authorization": "token " + token},
                    params={"format": "text"},
                )
                require(
                    saved.status_code == 200
                    and saved.json()["content"] == content.decode(),
                    "Reapplied instance cannot read the retained workspace file",
                )
                self.release(container)
                self.released([container])
                self.state(4)
                self.release(container)
                self.released([container])
                self.state(4)
                containers.append(container)
            return {
                "cycles": len(containers),
                "new_container_ids": containers,
                "workspace_preserved": True,
                "old_release_cannot_free_reallocated_gpu": True,
            }
        finally:
            user.client.post("/storage/delete", json={"path": filename})

    def two_multi_gpu_instances(self):
        user, other = self.accounts[:2]
        first = self.accepted(user, 2)
        self.wait([first])
        self.state(2)
        self.assert_denied(other, 3)
        second = self.accepted(user, 2)
        self.wait([second])
        self.state(0)
        devices = self.disjoint_workloads([(first, 2), (second, 2)])
        self.assert_denied(other, 1)
        self.release(first)
        self.released([first])
        self.state(2)
        replacement = self.accepted(other)
        self.wait([replacement])
        self.state(1)
        self.disjoint_workloads([(second, 2), (replacement, 1)])
        self.release_many([second, replacement])
        self.state(4)
        return {
            "simultaneous_instances": devices,
            "released_capacity_reused_by_another_user": True,
        }

    def four_gpu_instance(self):
        container = self.accepted(self.accounts[0], 4)
        self.wait([container])
        self.state(0)
        devices = self.workload(container, 4)
        self.assert_denied(self.accounts[1], 1)
        self.release(container)
        self.released([container])
        self.state(4)
        return {"gpu_count": 4, "gpu_uuids": devices, "all_four_computed": 42}

    def parallel_instances(self, different_users):
        details = []
        users = self.accounts[1:5] if different_users else [self.accounts[0]] * 4
        for round_index in range(self.args.rounds):
            # 不同用户使用相同的 key，验证幂等作用域不会混淆用户。
            shared_key = self.key("user-scope")
            keys = (
                [shared_key] * 4
                if different_users
                else [self.key("independent") for _ in users]
            )
            results = self.batch(
                [lambda a=a, k=k: self.apply(a, key=k) for a, k in zip(users, keys)]
            )
            require(
                all(r["http_status"] == 200 for r in results),
                f"Independent parallel apply failed: {results}",
            )
            containers = [r["container_id"] for r in results]
            require(
                len(set(containers)) == 4,
                "Independent applications were collapsed into one instance",
            )
            self.wait(containers)
            counts = self.state(0)
            devices = self.disjoint_workloads([(c, 1) for c in containers])
            self.assert_denied(self.accounts[7], 1)
            if different_users:
                for user, container, key in zip(users, containers, keys):
                    replay = self.apply(user, key=key)
                    require(
                        replay.get("container_id") == container,
                        "Retry returned another user's instance",
                    )
                    visible = user.client.get("/resource/my").json()["data"]
                    require(
                        not (set(containers) - {container}).intersection(
                            r["container_id"] for r in visible
                        ),
                        "User instance list exposed another user's instance",
                    )
                unauthorized = users[1].client.post(
                    "/resource/release", json={"container_id": containers[0]}
                )
                require(
                    unauthorized.status_code in (403, 404),
                    "Cross-user release was permitted",
                )
                self.state(0)
            self.release_many(containers)
            self.state(4)
            details.append(
                {"round": round_index + 1, "counts": counts, "workloads": devices}
            )
            self.emit(
                event="parallel_round_passed",
                different_users=different_users,
                round=round_index + 1,
            )
        return {"round_results": details}

    def last_gpu_contention(self):
        results = []
        for round_index in range(self.args.rounds):
            holder = self.accepted(self.accounts[0], 3)
            self.wait([holder])
            self.state(1)
            contenders = self.accounts[1:8]
            with SessionLocal() as db:
                balances = {
                    a.user_id: db.get(User, a.user_id).balance for a in contenders
                }
            responses = self.batch([lambda a=a: self.apply(a) for a in contenders])
            winners = [r for r in responses if r["http_status"] == 200]
            losers = [r for r in responses if r["http_status"] in (400, 409)]
            require(
                len(winners) == 1 and len(losers) == 6,
                f"Last GPU did not have exactly one winner: {responses}",
            )
            winner = winners[0]["container_id"]
            self.wait([winner])
            self.state(0)
            self.disjoint_workloads([(holder, 3), (winner, 1)])
            with SessionLocal() as db:
                for result in losers:
                    require(
                        db.get(User, result["user_id"]).balance
                        == balances[result["user_id"]],
                        "Losing contender was charged",
                    )
                    require(
                        db.query(GPU).filter_by(occupied_by=result["user_id"]).count()
                        == 0,
                        "Losing contender retained a GPU",
                    )
            self.release(winner)
            self.released([winner])
            self.state(1)
            loser = next(a for a in contenders if a.user_id == losers[0]["user_id"])
            recovered = self.accepted(loser)
            self.wait([recovered])
            self.state(0)
            self.workload(recovered, 1)
            self.release_many([holder, recovered])
            self.state(4)
            results.append(
                {
                    "round": round_index + 1,
                    "contenders": 7,
                    "accepted": 1,
                    "rejected_without_charge": 6,
                    "winner_user_id": winners[0]["user_id"],
                    "loser_reapplied_after_release": True,
                }
            )
            self.emit(
                event="last_gpu_round_passed",
                round=round_index + 1,
                winners=1,
                losers=6,
            )
        return {"round_results": results}

    def cleanup(self):
        # 即使 HTTP 响应丢失，也只找回本次请求已落库的实例，不遗漏其资源。
        with SessionLocal() as db:
            accounts = {a.user_id: a for a in self.accounts}
            for allocation in db.query(Allocation).filter(
                Allocation.request_id.in_(self.request_ids)
            ):
                if allocation.container_id and allocation.user_id in accounts:
                    self.tracked[allocation.container_id] = accounts[allocation.user_id]
        for container in list(self.tracked):
            try:
                self.release(container)
            except Exception as exc:
                self.report["cleanup_errors"].append(
                    {"container_id": container, "error": type(exc).__name__}
                )
        try:
            if self.tracked:
                self.released(list(self.tracked))
            self.report["final_counts"] = self.state(4)
            with SessionLocal() as db:
                for account in self.accounts:
                    allocation_ids = [
                        int(c.split("-")[1])
                        for c, a in self.tracked.items()
                        if a.user_id == account.user_id
                    ]
                    charged = sum(
                        (
                            r.amount
                            for r in db.query(BillingRecord).filter(
                                BillingRecord.allocation_id.in_(allocation_ids)
                            )
                        ),
                        Decimal(0),
                    )
                    require(
                        db.get(User, account.user_id).balance
                        == self.initial_balances[account.user_id] - charged,
                        "Account balance differs from the sum of its bills",
                    )
            self.report["balances_match_unique_bills"] = True
        except Exception as exc:
            self.report["cleanup_errors"].append(
                {
                    "error": type(exc).__name__,
                    "detail": str(exc) if isinstance(exc, CheckFailed) else None,
                }
            )

    def run(self):
        cases = [
            ("release_then_reapply", self.release_reapply),
            ("two_simultaneous_two_gpu_instances", self.two_multi_gpu_instances),
            ("one_four_gpu_instance", self.four_gpu_instance),
            (
                "one_user_four_independent_parallel_instances",
                lambda: self.parallel_instances(False),
            ),
            (
                "four_users_parallel_instances_and_isolation",
                lambda: self.parallel_instances(True),
            ),
            ("seven_users_compete_for_last_gpu", self.last_gpu_contention),
        ]
        if self.args.case:
            cases = [
                (name, execute) for name, execute in cases if name == self.args.case
            ]
            require(cases, "Unknown resource scenario")
        try:
            for name, execute in cases:
                self.emit(event="case_started", case=name)
                result = {"name": name, "passed": False}
                self.report["cases"].append(result)
                try:
                    result.update(execute())
                    result["passed"] = True
                    self.emit(event="case_passed", case=name)
                except Exception as exc:
                    result["failure"] = type(exc).__name__
                    result["detail"] = (
                        str(exc) if isinstance(exc, CheckFailed) else None
                    )
                    self.emit(event="case_failed", **result)
                    break
        finally:
            self.cleanup()
            self.report["created_instances"] = len(self.tracked)
            self.report["passed"] = (
                len(self.report["cases"]) == len(cases)
                and all(c["passed"] for c in self.report["cases"])
                and not self.report["cleanup_errors"]
            )
            output = json.dumps(self.report, indent=2, ensure_ascii=False)
            for secret in self.secrets:
                output = output.replace(secret, "[REDACTED]")
            output = re.sub(r"([?&]token=)[^&\s\"\'<>]+", r"\1[REDACTED]", output)
            Path(self.args.report).write_text(output, encoding="utf-8")
            self.emit(
                event="suite_finished",
                passed=self.report["passed"],
                created_instances=len(self.tracked),
                report=self.args.report,
            )
            for account in self.accounts:
                account.client.close()
            self.core.api_client.close()
        return self.report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--pool-id", required=True, type=int)
    parser.add_argument("--image-id", required=True, type=int)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--case", help="Only run the named scenario; omit to run the full suite"
    )
    parser.add_argument("--startup-timeout", type=int, default=180)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    require(args.rounds >= 1, "rounds must be positive")
    suite = ResourceScenarios(args, json.load(sys.stdin))
    return 0 if suite.run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
