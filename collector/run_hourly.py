"""Chạy mỗi giờ trên GitHub Actions: lấy tin mới -> lọc -> tra token -> tóm tắt -> ghi D1.

Biến môi trường: TG_API_ID, TG_API_HASH, TG_SESSION, GROQ_API_KEY, (GEMINI_API_KEY),
CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN. Đặt HIDE_NAMES=1 để log không lộ tên nhóm.
"""
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dexscreener  # noqa: E402
import summarize as sm  # noqa: E402
import telegram_fetch  # noqa: E402
import web_fetch  # noqa: E402
from d1 import D1  # noqa: E402
from filters import filter_messages  # noqa: E402

VN = timezone(timedelta(hours=7))
KEEP_DAYS = 365


def log(msg):
    print(msg, flush=True)


def vn_day(iso):
    return datetime.fromisoformat(iso).astimezone(VN).strftime("%Y-%m-%d")


def vn_hour(iso):
    return datetime.fromisoformat(iso).astimezone(VN).strftime("%Y-%m-%d %H:00")


def start_of_today():
    now = datetime.now(VN)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def load_sources(db):
    rows = db.query("SELECT kind, value, title FROM sources")
    out = {"telegram": [], "website": [], "sender": []}
    for r in rows:
        out.setdefault(r["kind"], []).append(r)
    return out


def tg_key(v):
    v = str(v).strip()
    return int(v) if v.lstrip("-").isdigit() else v


def tg_creds(db):
    """Ưu tiên secret trên GitHub nếu hợp lệ; nếu không, dùng bản lưu trong database."""
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    session = os.environ.get("TG_SESSION", "").strip()
    if api_id.isdigit() and len(api_hash) == 32 and len(session) > 100:
        return api_id, api_hash, session
    saved = db.get_state("tg_creds")
    if not saved:
        raise SystemExit("Secret TG_API_ID / TG_API_HASH / TG_SESSION chưa đúng và database không có bản dự phòng.")
    log("[telegram] dùng thông tin đăng nhập lưu trong database")
    return saved["api_id"], saved["api_hash"], saved["session"]


async def fetch_telegram(groups, min_ids, creds):
    api_id, api_hash, session = creds
    client = telegram_fetch.make_client(session, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("TG_SESSION hết hạn hoặc sai. Tạo session string mới bằng notebook Colab rồi cập nhật secret.")
    info = {}
    try:
        keys = [str(g["value"]) for g in groups]
        names = {str(g["value"]): g.get("title") for g in groups}
        mins = {tg_key(k): min_ids[k] for k in keys if min_ids.get(k)}
        msgs, ginfo, max_ids = await telegram_fetch.fetch_async(client, [tg_key(k) for k in keys], start_of_today(), mins)
        for gid, gi in ginfo.items():
            info[str(gid)] = {"real_title": gi["title"]}
        for m in msgs:
            m["group"] = names.get(str(m["group_id"])) or m["group"]
        for gid, mx in max_ids.items():
            min_ids[str(gid)] = max(min_ids.get(str(gid)) or 0, mx)
    finally:
        await client.disconnect()
    return msgs, info


def main():
    keys = {"gemini": os.environ.get("GEMINI_API_KEY", ""), "groq": os.environ.get("GROQ_API_KEY", "")}
    db = D1()
    src = load_sources(db)
    now = datetime.now(timezone.utc)
    log(f"[nguồn] {len(src['telegram'])} nhóm, {len(src['website'])} trang web, {len(src['sender'])} người theo dõi")

    # người theo dõi lấy từ database
    import filters
    filters._WATCH_SENDERS = {str(r["value"]).lstrip("@").lower() for r in src["sender"]}

    # 1. Telegram
    min_ids = db.get_state("min_ids", {})
    msgs, info = ([], {})
    if src["telegram"]:
        msgs, info = asyncio.run(fetch_telegram(src["telegram"], min_ids, tg_creds(db)))
    # cập nhật tên nhóm thật nếu người dùng chưa đặt tên
    for r in src["telegram"]:
        i = info.get(str(r["value"]))
        if i and not r.get("title"):
            db.query("UPDATE sources SET title = ? WHERE kind = 'telegram' AND value = ?", [i["real_title"], r["value"]])

    # 2. Trang web (RSS), bỏ bài đã lưu
    if src["website"]:
        last_web = db.get_state("last_web_run")
        since = datetime.fromisoformat(last_web) - timedelta(hours=2) if last_web else start_of_today()
        wmsgs, _ = web_fetch.fetch([{"url": r["value"], "title": r.get("title")} for r in src["website"]], since)
        uids = [m["uid"] for m in wmsgs]
        seen = set()
        for i in range(0, len(uids), 90):
            part = uids[i:i + 90]
            seen |= {r["uid"] for r in db.query(
                f"SELECT uid FROM messages WHERE uid IN ({','.join('?' * len(part))})", part)}
        msgs += [m for m in wmsgs if m["uid"] not in seen]
        db.set_state("last_web_run", now.isoformat())
    log(f"[đọc] {len(msgs)} tin mới")

    kept, stats = filter_messages(msgs)
    log(f"[lọc] {stats}")
    days = sorted({vn_day(m["date"]) for m in kept} | {datetime.now(VN).strftime("%Y-%m-%d")})
    today = datetime.now(VN).strftime("%Y-%m-%d")

    # 3. Token: CA mới + CA đã nhắc hôm nay (cập nhật giá)
    mentions = defaultdict(lambda: {"count": 0, "groups": set(), "first": None, "links": []})
    for m in kept:
        for ca in m["contracts"]:
            x = mentions[ca]
            x["count"] += 1
            x["groups"].add(m["group"])
            x["first"] = min(filter(None, [x["first"], m["date"]]))
            if len(x["links"]) < 5:
                x["links"].append(m["link"])
    old_today = {r["address"]: json.loads(r["data"]) for r in
                 db.query("SELECT address, data FROM token_days WHERE day = ?", [today])}
    dex = dexscreener.lookup(list(dict.fromkeys(list(mentions) + list(old_today)))) if (mentions or old_today) else {}
    valid = set(dex)
    for m in kept:
        m["contracts"] = [c for c in m["contracts"] if c in valid]
    known = {}
    addrs = list(dex)
    for i in range(0, len(addrs), 90):
        part = [a.lower() if a.startswith("0x") else a for a in addrs[i:i + 90]]
        for r in db.query(f"SELECT * FROM tokens WHERE address IN ({','.join('?' * len(part))})", part):
            known[r["address"]] = r
    new_tokens, token_rows = [], []
    for ca, info_ in dex.items():
        key = ca.lower() if ca.startswith("0x") else ca
        prev = old_today.get(ca, {})
        mm = mentions.get(ca)
        t = {**info_,
             "mentions": prev.get("mentions", 0) + (mm["count"] if mm else 0),
             "groups": sorted(set(prev.get("groups", [])) | (mm["groups"] if mm else set())),
             "first_seen": prev.get("first_seen") or (mm["first"] if mm else None),
             "msg_links": (prev.get("msg_links", []) + (mm["links"] if mm else []))[:5]}
        k = known.get(key)
        if k and k.get("first_price") and t.get("price_usd"):
            t["base_price"], t["base_at"] = k["first_price"], k["first_at"]
            t["first_mention"] = k.get("first_mention")
            t["change_since_first"] = (t["price_usd"] / k["first_price"] - 1) * 100
        else:
            t["change_since_first"] = None
            if t.get("price_usd"):
                new_tokens.append([key, t["price_usd"], t["price_at"], t["first_seen"], t.get("symbol")])
        token_rows.append([today, ca, json.dumps(t, ensure_ascii=False)])
    db.upsert("tokens", ["address", "first_price", "first_at", "first_mention", "symbol"], new_tokens, conflict=["address"])
    db.upsert("token_days", ["day", "address", "data"], token_rows, conflict=["day", "address"])
    log(f"[token] {len(dex)} token, {len(new_tokens)} lần đầu")

    # 4. Lưu tin, theo dõi, link
    db.upsert("messages", ["uid", "day", "date", "data"], [[m["uid"], vn_day(m["date"]), m["date"], json.dumps({
        "link": m["link"], "group": m["group"], "date": m["date"], "sender": m.get("sender"), "text": m["text"][:400]},
        ensure_ascii=False)] for m in kept], conflict=["uid"])
    db.upsert("watch", ["uid", "day", "date", "data"], [[m["uid"], vn_day(m["date"]), m["date"], json.dumps({
        "uid": m["uid"], "tags": m["watch"], "group": m["group"], "date": m["date"], "sender": m.get("sender"),
        "username": m.get("sender_username"), "text": m["text"][:1500], "links": m["links"][:5],
        "contracts": m["contracts"], "link": m["link"]}, ensure_ascii=False)] for m in kept if m["watch"]],
        conflict=["uid"])
    link_rows = {}
    for m in kept:
        for u in m["links"]:
            link_rows[(u, vn_day(m["date"]))] = [u, vn_day(m["date"]), m["date"], json.dumps({
                "url": u, "group": m["group"], "date": m["date"], "topics": m["topics"],
                "context": m["text"][:200], "msg": m["link"]}, ensure_ascii=False)]
    db.upsert("links", ["url", "day", "date", "data"], list(link_rows.values()), conflict=["url", "day"])

    # 5. Tóm tắt theo giờ (gộp với phần đã có của giờ đó nếu lượt trước đã chạy)
    by_hour = defaultdict(list)
    for m in kept:
        if m["topics"]:
            by_hour[vn_hour(m["date"])].append(m)
    for h, ms in sorted(by_hour.items()):
        log(f"[AI] tóm tắt {h} ({len(ms)} tin)")
        res = sm.summarize(keys, ms, f"{h} (giờ Việt Nam), 60 phút")
        old = db.query("SELECT data FROM hours WHERE hour = ?", [h])
        if old:
            o = json.loads(old[0]["data"])
            res = {"overview": (o.get("overview", "") + " " + res["overview"]).strip()[:1200],
                   "events": o.get("events", []) + res["events"], "count": o.get("count", 0) + len(ms)}
        else:
            res["count"] = len(ms)
        db.upsert("hours", ["hour", "day", "data"], [[h, h[:10], json.dumps({"hour": h, "span": 1, **res},
                                                                             ensure_ascii=False)]], conflict=["hour"])

    # 6. Tổng hợp ngày (chỉ khi có tin mới)
    for d in {h[:10] for h in by_hour}:
        hours = [json.loads(r["data"]) for r in db.query("SELECT data FROM hours WHERE day = ?", [d])]
        events = [e for h in hours for e in h.get("events", [])]
        log(f"[AI] tổng hợp ngày {d} ({len(events)} sự kiện)")
        digest = sm.merge_events(keys, events, f"ngày {d}")
        db.upsert("digests", ["day", "data", "updated_at"], [[d, json.dumps(digest, ensure_ascii=False),
                                                              now.isoformat()]], conflict=["day"])

    # 7. Thống kê ngày + trạng thái
    for d in days:
        st = db.query("SELECT data FROM stats WHERE day = ?", [d])
        cur = json.loads(st[0]["data"]) if st else {}
        part = [m for m in msgs if vn_day(m["date"]) == d]
        kpart = [m for m in kept if vn_day(m["date"]) == d]
        cur["total"] = cur.get("total", 0) + len(part)
        cur["kept"] = cur.get("kept", 0) + len(kpart)
        cur["watch"] = cur.get("watch", 0) + sum(1 for m in kpart if m["watch"])
        db.upsert("stats", ["day", "data"], [[d, json.dumps(cur)]], conflict=["day"])
    db.set_state("min_ids", min_ids)
    db.set_state("last_run", now.isoformat())

    # 8. Xoá dữ liệu cũ hơn 1 năm
    cutoff = (datetime.now(VN) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for t in ("hours", "digests", "messages", "watch", "links", "token_days", "stats"):
        db.query(f"DELETE FROM {t} WHERE day < ?", [cutoff])
    log("[xong]")


if __name__ == "__main__":
    main()
