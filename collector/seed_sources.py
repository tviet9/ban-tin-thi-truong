"""Ghi danh sách nguồn vào D1 từ biến SEED_JSON: {"telegram": [...], "sender": [...], "website": [...]}.
Chỉ in số lượng, không in nội dung (repo công khai)."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d1 import D1  # noqa: E402

data = json.loads(os.environ["SEED_JSON"])
now = datetime.now(timezone.utc).isoformat()
rows = [[kind, str(v).strip(), None, now] for kind in ("telegram", "sender", "website") for v in data.get(kind, [])]
D1().upsert("sources", ["kind", "value", "title", "created_at"], rows, conflict=["kind", "value"])
print(f"Đã ghi {len(rows)} nguồn: " + ", ".join(f"{k}={len(data.get(k, []))}" for k in ("telegram", "sender", "website")))
