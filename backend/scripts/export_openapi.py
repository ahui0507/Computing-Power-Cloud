"""从应用契约导出仓库 API.yaml，不连接数据库或集群。"""
import sys
from pathlib import Path

import yaml

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.main import app


if __name__ == "__main__":
    destination = backend_dir.parent / "API.yaml"
    destination.write_text(
        yaml.safe_dump(app.openapi(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Exported {len(app.openapi()['paths'])} API paths")
