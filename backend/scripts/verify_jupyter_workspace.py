"""核对在真实 JupyterLab 界面创建、执行并下载的验收 Notebook。

普通用户账号 JSON 从标准输入读取。inspect 核对运行中实例的文件和鉴权，
persistence 在释放后核对文件仍可下载。报告不记录密码或访问令牌。
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def text(value):
    return "".join(value) if isinstance(value, list) else value


def notebook_projection(notebook):
    return [
        {
            "type": cell["cell_type"],
            "source": text(cell["source"]),
            "execution_count": cell.get("execution_count"),
            "outputs": [
                {"type": output["output_type"], "text": text(output.get("text", ""))}
                for output in cell.get("outputs", [])
            ],
        }
        for cell in notebook["cells"]
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["inspect", "persistence"])
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--notebook", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--uploaded-file", required=True)
    parser.add_argument("--download-projection-sha256", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    state = json.loads(Path(args.state).read_text())
    report_path = Path(args.report)
    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=30) as client:
        login = client.post("/auth/login", json=credentials)
        check(login.status_code == 200, "Ordinary user login failed")
        client.headers["Authorization"] = "Bearer " + login.json()["data"]["token"]
        owner = client.get("/auth/user_info").json()["data"]
        check(owner["role"] == "user" and owner["user_id"] == state["user_id"], "Wrong test owner")
        resources = client.get("/resource/my").json()["data"]
        workload = next(r for r in resources if r["container_id"] == state["container_id"])

        def download(filename):
            response = client.get("/storage/download", params={"path": filename})
            check(
                response.status_code == 200,
                "A test file cannot be downloaded from platform storage",
            )
            return response.content

        if args.phase == "persistence":
            report = json.loads(report_path.read_text())
            check(
                report["container_id"] == workload["container_id"],
                "Report belongs to another instance",
            )
            check(workload["status"] == "released", "Test instance has not been released")
            for filename, expected in report["file_sha256"].items():
                check(
                    hashlib.sha256(download(filename)).hexdigest() == expected,
                    "File changed or disappeared after release",
                )
            pools = client.get("/resource/pools").json()["data"]
            free = next(p["free_gpus"] for p in pools if p["pool_id"] == 1)
            check(free == state["initial_free_gpus"], "GPU capacity was not recovered")
            report.update(passed=True, files_persist_after_release=True, final_free_gpus=free)
        else:
            check(workload["status"] == "running", "Test instance is not running")
            url = urlsplit(workload["jupyter_url"])
            from urllib.parse import parse_qs

            token = parse_qs(url.query)["token"][0]
            base = urlunsplit((url.scheme, url.netloc, url.path.rstrip("/") + "/", "", ""))
            auth = {"Authorization": "token " + token}
            contents_url = base + "api/contents/" + quote(args.notebook)
            anonymous = httpx.get(contents_url, timeout=15)
            wrong = httpx.get(
                contents_url,
                headers={"Authorization": "token invalid-acceptance-token"},
                timeout=15,
            )
            check(
                anonymous.status_code == wrong.status_code == 403,
                "Notebook API authentication failed",
            )
            response = client.get(contents_url, headers=auth)
            check(response.status_code == 200, "Authorized notebook read failed")
            notebook = json.loads(download(args.notebook))
            projection = notebook_projection(notebook)
            check(
                projection == notebook_projection(response.json()["content"]),
                "Jupyter and platform storage disagree",
            )
            digest = hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()
            check(
                digest == args.download_projection_sha256,
                "GUI notebook download differs from saved content",
            )
            code = [cell for cell in projection if cell["type"] == "code"]
            check(
                len(code) == 6 and [c["execution_count"] for c in code] == list(range(1, 7)),
                "Not all six notebook cells were rerun and saved",
            )
            expected = [
                "JupyterLab is working\n42\n",
                "Notebook saved 42\n",
                "Hello, cloud platform!\n1 + 1 = 2\n",
                "Visible GPUs: 1\n",
                "Old variable survives restart: False\n",
                "Kernel recovered after interrupt\n",
            ]
            actual = ["".join(o["text"] for o in cell["outputs"]) for cell in code]
            check(actual == expected, "Saved notebook output differs from expected UI execution")
            check(
                all(o["type"] == "stream" for cell in code for o in cell["outputs"]),
                "Saved notebook contains an unexpected error/output",
            )
            check(
                projection[0]["type"] == "markdown"
                and "JupyterLab acceptance" in projection[0]["source"],
                "Markdown cell was not retained",
            )
            file_hashes = {args.notebook: hashlib.sha256(download(args.notebook)).hexdigest()}
            for filename, expected_text in (
                (args.result_file, "Notebook saved 42"),
                (args.uploaded_file, "Uploaded through JupyterLab GUI.\n"),
            ):
                data = download(filename)
                check(
                    data.decode() == expected_text,
                    "GUI upload or notebook file write did not persist",
                )
                jupyter = client.get(
                    base + "api/contents/" + quote(filename),
                    headers=auth,
                    params={"format": "text"},
                )
                check(
                    jupyter.status_code == 200 and jupyter.json()["content"] == expected_text,
                    "Jupyter file view differs from platform storage",
                )
                file_hashes[filename] = hashlib.sha256(data).hexdigest()
            sessions = client.get(base + "api/sessions", headers=auth).json()
            matching = [s for s in sessions if s["path"] == args.notebook]
            check(
                len(matching) == 1 and matching[0]["kernel"]["execution_state"] == "idle",
                "Notebook kernel is not healthy and idle",
            )
            terminals = client.get(base + "api/terminals", headers=auth)
            check(
                terminals.status_code == 200 and terminals.json(),
                "JupyterLab terminal was not created",
            )
            api = client.get(base + "api", headers=auth).json()
            report = {
                "passed": False,
                "inspection_passed": True,
                "container_id": workload["container_id"],
                "role": owner["role"],
                "notebook": args.notebook,
                "nbformat": notebook["nbformat"],
                "executed_code_cells": len(code),
                "execution_counts": list(range(1, 7)),
                "saved_outputs": actual,
                "markdown_saved": True,
                "gui_download_matches": True,
                "shared_file_reads_match": True,
                "anonymous_http_status": anonymous.status_code,
                "wrong_token_http_status": wrong.status_code,
                "kernel_status": "idle",
                "terminal_api_available": True,
                "jupyter_server_version": api.get("version"),
                "file_sha256": file_hashes,
            }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "inspection_passed": report["inspection_passed"],
                    "passed": report["passed"],
                    "notebook": args.notebook,
                    "executed_code_cells": report["executed_code_cells"],
                }
            ),
            flush=True,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
