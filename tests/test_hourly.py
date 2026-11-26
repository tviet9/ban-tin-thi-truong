"""Chạy thử run_hourly với database SQLite giả lập D1, Telegram/DexScreener/AI giả. Không cần mạng.
python3 tests/test_hourly.py <đường dẫn file sqlite>
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

import d1  # noqa: E402
import run_hourly  # noqa: E402

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test_bantin.sqlite"


class SqliteD1(d1.D1):
    def __init__(self):
        self.con = sqlite3.connect(DB_PATH)
        self.con.row_factory = sqlite3.Row

    def query(self, sql, params=None):
        cur = self.con.execute(sql, list(params or []))
        rows = [dict(r) for r in cur.fetchall()]
        self.con.commit()
        return rows


def setup():
    Path(DB_PATH).unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript((ROOT / "worker" / "schema.sql").read_text())
    now = datetime.now(timezone.utc).isoformat()
    con.executemany("INSERT INTO sources VALUES (?,?,?,?)", [
        ("telegram", "-1001", None, now), ("telegram", "-1002", "Tin vĩ mô", now), ("sender", "admin_vimo", None, now),
        ("x", "https://rss.app/feeds/elon.xml", "@elonmusk", now), ("flow", "-1003", "Cá voi (mẫu)", now)])
    con.commit()


def fake_messages():
    raw = json.loads((ROOT / "tests" / "sample_messages.json").read_text(encoding="utf-8"))["messages"]
    base = datetime.now(timezone.utc) - timedelta(minutes=50)
    out = []
    for i, m in enumerate(raw):
        m = dict(m)
        m["group_id"] = -1001 if m["group_id"] != 2 else -1002
        m["date"] = (base + timedelta(minutes=i * 2)).isoformat()
        out.append(m)
    # kênh Dòng tiền: tin không có từ khoá chủ đề vẫn phải được giữ
    for i, t in enumerate(["🐳 5,000 ETH chuyển từ ví lạ vào Binance", "Ví quỹ A rút 20 triệu USDT khỏi OKX"]):
        out.append({"uid": f"1003-{i}", "id": 9000 + i, "group_id": -1003, "group": "Cá voi (mẫu)", "sender": "Bot",
                    "sender_id": 1, "sender_username": None, "text": t, "urls": [],
                    "date": (base + timedelta(minutes=40 + i)).isoformat(), "link": f"https://t.me/c/1003/{i}"})
    return out


def main():
    setup()
    run_hourly.D1 = SqliteD1
    sample_dex = json.loads((ROOT / "tests" / "sample_dex.json").read_text(encoding="utf-8"))
    for v in sample_dex.values():
        v["price_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    LOTUS = "9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT"
    # lượt 1: DexScreener chưa ghi nhận LOTUS -> phải vào danh sách chờ, lượt sau tra lại được
    run_hourly.dexscreener.lookup = lambda addrs: {a: dict(sample_dex[a]) for a in addrs if a in sample_dex and a != LOTUS}

    run_hourly.tg_creds = lambda: ("1", "a" * 32, "s" * 200)

    async def fake_tg(groups, min_ids, creds):
        msgs = fake_messages()
        for gid in ("-1001", "-1002"):
            min_ids[gid] = 2000
        return msgs, {"-1001": {"real_title": "Nhóm Crypto (thật)"}, "-1002": {"real_title": "x"}, "-1003": {"real_title": "y"}}
    run_hourly.fetch_telegram = fake_tg
    digest = json.loads((ROOT / "tests" / "sample_digest.json").read_text(encoding="utf-8"))

    def fake_call(keys, system, text):
        ids = [ln[1:ln.index("]")] for ln in text.splitlines() if ln.startswith("[")]
        if "Events:" in text:
            return json.loads(json.dumps(digest))
        return {"overview": f"{len(ids)} tin.", "events": [
            {"topic": "crypto", "tags": [], "title": "Sự kiện giờ", "points": ["10:00 · ý"], "importance": 3,
             "source_ids": ids[:2]}]}
    run_hourly.sm.call = fake_call
    base = datetime.now(timezone.utc) - timedelta(minutes=20)

    def fake_web(sites, since, site_offset=100, **kw):
        out = []
        if not sites:
            return [], []
        for i, t in enumerate(["$DOGE to the moon, Fed lãi suất #crypto", "$doge pump again @cz_binance",
                               "CA 9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT", "Ăn sáng thôi"]):
            out.append({"uid": f"w-x{i}", "id": i, "group_id": "x", "group": sites[0]["title"], "sender": None,
                        "date": (base + timedelta(minutes=i)).isoformat(), "text": t, "urls": [],
                        "link": f"https://nitter.example/elonmusk/status/{i}#m", "source": "web", "raw_title": t})
        return out, []
    run_hourly.web_fetch.fetch = fake_web
    run_hourly.fulltext.enrich = lambda msgs, health, log=print, **kw: 0  # không gọi mạng trong test
    run_hourly.main()
    con0 = sqlite3.connect(DB_PATH)
    pend = json.loads(con0.execute("SELECT value FROM state WHERE key='ca_pending'").fetchone()[0])
    assert LOTUS in pend and not con0.execute("SELECT 1 FROM token_days WHERE address=?", [LOTUS]).fetchone(), pend.keys()
    run_hourly.dexscreener.lookup = lambda addrs: {a: dict(sample_dex[a]) for a in addrs if a in sample_dex}
    run_hourly.main()  # lượt chờ: LOTUS được tra lại và lên bảng với đúng người gửi đầu
    lot = json.loads(con0.execute("SELECT data FROM token_days WHERE address=?", [LOTUS]).fetchone()[0])
    pend = json.loads(con0.execute("SELECT value FROM state WHERE key='ca_pending'").fetchone()[0])
    assert lot["first_sender"] and lot["first_group"] and LOTUS not in pend, (lot.get("first_sender"), pend.keys())
    # chạy lần 2: không có tin mới, token đã có giá lần đầu
    run_hourly.fetch_telegram = lambda g, m, c: _empty()
    run_hourly.main()
    # lượt 3 (30 phút sau): có tin mới nhưng AI vừa gộp ngày -> chỉ nối sự kiện vào bản tổng hợp, không gọi AI gộp
    con = sqlite3.connect(DB_PATH)
    before = len(json.loads(con.execute("SELECT data FROM digests").fetchone()[0])["events"])
    merges = []
    real_merge = run_hourly.sm.merge_events
    run_hourly.sm.merge_events = lambda *a, **k: merges.append(1) or real_merge(*a, **k)

    async def fake_tg3(groups, min_ids, creds):
        ms = fake_messages()
        for m in ms:
            m["uid"] += "-n"
        return ms, {"-1001": {"real_title": "Nhóm Crypto (thật)"}, "-1002": {"real_title": "x"}, "-1003": {"real_title": "y"}}
    run_hourly.fetch_telegram = fake_tg3
    run_hourly.main()
    after = len(json.loads(con.execute("SELECT data FROM digests").fetchone()[0])["events"])
    pend = json.loads(con.execute("SELECT value FROM state WHERE key='merge_pending'").fetchone()[0])
    assert not merges and after > before and pend, (merges, before, after, pend)
    # lượt 4: đã quá giờ gộp -> AI gộp lại ngày đang chờ dù không có tin mới
    run_hourly.MERGE_EVERY_MIN = 0
    run_hourly.fetch_telegram = lambda g, m, c: _empty()
    run_hourly.main()
    pend = json.loads(con.execute("SELECT value FROM state WHERE key='merge_pending'").fetchone()[0])
    assert merges and not pend, (merges, pend)
    run_hourly.sm.merge_events = real_merge
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("hours", "digests", "messages", "watch", "links", "tokens", "token_days", "stats")}
    print("rows:", counts)
    title = con.execute("SELECT title FROM sources WHERE value='-1001'").fetchone()[0]
    assert title == "Nhóm Crypto (thật)", title
    xp = con.execute("SELECT COUNT(*) FROM x_posts").fetchone()[0]
    tr = json.loads(con.execute("SELECT data FROM x_trend").fetchone()[0])
    assert xp == 4, xp
    assert tr[0]["term"] == "$DOGE" and tr[0]["count"] == 2, tr[:2]
    assert any(json.loads(r[0]).get("x") for r in con.execute("SELECT data FROM token_days")), "CA nhắc trên X phải có cờ x"
    td = {json.loads(r[0])["symbol"]: json.loads(r[0]) for r in con.execute("SELECT data FROM token_days")}
    assert td["MEOW"]["first_group"] and td["MEOW"]["first_seen"] and td["MEOW"]["first_sender"], td["MEOW"]
    assert not any("dexscreener.com" in r[0] for r in con.execute("SELECT url FROM links")), "link dexscreener phải bị bỏ"
    assert counts["digests"] == 1 and counts["tokens"] == 2 and counts["watch"] >= 1 and counts["messages"] > 10
    td = [json.loads(r[0]) for r in con.execute("SELECT data FROM token_days")]
    assert all(t["change_since_first"] is not None for t in td), "lần 2 phải có % so với lần đầu"
    flows = [json.loads(r[0]) for r in con.execute("SELECT data FROM watch") if '"dong_tien"' in r[0]]
    assert len(flows) == 4 and all(f["group"] == "Cá voi (mẫu)" for f in flows), len(flows)  # 2 tin x 2 lượt (lượt 3 lặp tin với mã mới)
    fsum = json.loads(con.execute("SELECT data FROM flow_sum").fetchone()[0])
    assert fsum["count"] == 4 and fsum["events"], fsum
    hs = json.loads(con.execute("SELECT value FROM state WHERE key='source_health'").fetchone()[0])
    assert "ok_at" in hs.get("flow:-1003", {}), hs.keys()
    assert "ok_at" in hs.get("telegram:-1001", {}), hs
    print("test_hourly OK")


async def _empty():
    return [], {}


if __name__ == "__main__":
    main()
