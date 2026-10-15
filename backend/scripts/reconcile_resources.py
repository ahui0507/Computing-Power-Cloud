"""运行一次资源对账，适合受控运维和故障恢复。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.reconciliation_service import run_reconciliation_once


if __name__ == "__main__":
    print(json.dumps(run_reconciliation_once(), ensure_ascii=False))
