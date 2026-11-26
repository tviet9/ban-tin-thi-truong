"""Chẩn đoán vì sao một CA không lên bảng token. Repo công khai: chỉ in giờ, CA, kết quả tra, KHÔNG in nội dung tin/tên nhóm.
Chạy: python scripts/diag_ca.py <từ giờ UTC ISO> <đến giờ UTC ISO> [chuỗi trong tên nhóm]
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))
import dexscreener  # noqa: E402
from d1 import D1  # noqa: E402
from filters import extract_contracts  # noqa: E402

if sys.argv[1] == "health":  # in trạng thái nguồn đang lỗi (che bớt ID/link vì log công khai)
    h = json.loads((D1().query("SELECT value FROM state WHERE key='source_health'") or [{"value": "{}"}])[0]["value"])
    for k, v in sorted(h.items()):
        bad = v.get("err_at") and (not v.get("ok_at") or v["err_at"] > v["ok_at"])
        kind, val = k.split(":", 1)
        print(f"{'LỖI' if bad else 'ok '} {kind}:{val[:6]}…{val[-4:]} ok={v.get('ok_at')} lỗi={v.get('err_at')} {v.get('err') if bad else ''}")
    sys.exit(0)
t0, t1 = sys.argv[1], sys.argv[2]
grp = (sys.argv[3] if len(sys.argv) > 3 else "").lower()
db = D1()
rows = db.query("SELECT uid, date, data FROM messages WHERE date >= ? AND date <= ? ORDER BY date", [t0, t1])
print(f"tin đã lưu trong khoảng: {len(rows)}")
toks = {r["address"] for r in db.query("SELECT address FROM token_days WHERE day >= ?", [t0[:10]])}
seen = set()
for r in rows:
    d = json.loads(r["data"])
    if grp and grp not in (d.get("group") or "").lower():
        continue
    cas = extract_contracts(d.get("text") or "")
    if not cas:
        continue
    for ca in cas:
        if ca in seen:
            continue
        seen.add(ca)
        alone = dexscreener.lookup([ca]) or {}
        raw = dexscreener._get(dexscreener.API + ca) or {}
        print(f"{r['date'][:16]} CA {ca} | trong bảng: {ca in toks} | tra riêng DexScreener: {'CÓ ' + str(alone[ca]['symbol']) if ca in alone else 'KHÔNG'}"
              f" | số cặp: {len(raw.get('pairs') or [])} | độ dài tin {len(d.get('text') or '')}")
print("xong")
