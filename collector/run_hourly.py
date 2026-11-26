"""Chạy mỗi 20 phút trên GitHub Actions: lấy tin mới -> lọc -> tra token -> tóm tắt -> ghi D1.

Biến môi trường: TG_API_ID, TG_API_HASH, TG_SESSION, GROQ_API_KEY, (GEMINI_API_KEY),
CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN. Đặt HIDE_NAMES=1 để log không lộ tên nhóm.
"""
import asyncio
import json
import re
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dexscreener  # noqa: E402
import fulltext  # noqa: E402
import youtube_fetch  # noqa: E402
from health import Health  # noqa: E402
import summarize as sm  # noqa: E402
import telegram_fetch  # noqa: E402
import web_fetch  # noqa: E402
import x_fetch  # noqa: E402
from x_trend import trending  # noqa: E402
from d1 import D1  # noqa: E402
from config import LINK_SKIP_DOMAINS  # noqa: E402
from filters import filter_messages  # noqa: E402

VN = timezone(timedelta(hours=7))
KEEP_DAYS = 365
MERGE_EVERY_MIN = 55  # AI gộp lại bản tổng hợp ngày tối đa mỗi giờ một lần (lượt 20 phút xen giữa chỉ nối thêm)


def log(msg):
    print(msg, flush=True)


def vn_day(iso):
    return datetime.fromisoformat(iso).astimezone(VN).strftime("%Y-%m-%d")


def vn_hour(iso):
    return datetime.fromisoformat(iso).astimezone(VN).strftime("%Y-%m-%d %H:00")


def backfill_since():
    """BACKFILL_FROM=YYYY-MM-DD: đọc lại tin từ 0h (giờ VN) của ngày đó."""
    d = os.environ.get("BACKFILL_FROM", "").strip()
    if not d:
        return None
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=VN).astimezone(timezone.utc)


def start_of_today():
    now = datetime.now(VN)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def load_sources(db):
    rows = db.query("SELECT kind, value, title FROM sources ORDER BY kind, value")
    out = {"telegram": [], "website": [], "sender": [], "x": [], "youtube": []}
    for r in rows:
        out.setdefault(r["kind"], []).append(r)
    return out


def tg_key(v):
    v = str(v).strip()
    return int(v) if v.lstrip("-").isdigit() else v


def tg_creds():
    api_id = os.environ.get("TG_API_ID", "").strip()  # secret hay dính dấu xuống dòng
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    session = os.environ.get("TG_SESSION", "").strip()
    if not (api_id.isdigit() and len(api_hash) == 32 and len(session) > 100):
        raise SystemExit("Secret TG_API_ID / TG_API_HASH / TG_SESSION chưa đúng (kiểm tra lại giá trị trên GitHub).")
    return api_id, api_hash, session


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
        backfill = backfill_since()
        # Lấy lại từ một ngày cũ: bỏ qua mốc tin cuối, đọc lại từ 0h ngày đó (tin đã xử lý sẽ bị bỏ qua sau)
        mins = {} if backfill else {tg_key(k): min_ids[k] for k in keys if min_ids.get(k)}
        msgs, ginfo, max_ids = await telegram_fetch.fetch_async(client, [tg_key(k) for k in keys], backfill or start_of_today(), mins)
        for gid, gi in ginfo.items():
            info[str(gid)] = {"real_title": gi["title"]}
        for m in msgs:
            m["group"] = names.get(str(m["group_id"])) or m["group"]
        for gid, mx in max_ids.items():
            min_ids[str(gid)] = max(min_ids.get(str(gid)) or 0, mx)
    finally:
        await client.disconnect()
    return msgs, info


def reset_today(db):
    """Xoá dữ liệu hôm nay (dùng khi lượt trước lỗi giữa chừng). Giữ nguyên danh sách nguồn."""
    d = datetime.now(VN).strftime("%Y-%m-%d")
    for t in ("hours", "digests", "messages", "watch", "links", "token_days", "stats"):
        db.query(f"DELETE FROM {t} WHERE day = ?", [d])
    db.query("DELETE FROM tokens WHERE first_at >= ?", [start_of_today().isoformat(timespec="minutes")])
    db.query("DELETE FROM state WHERE key IN ('min_ids', 'last_run', 'last_web_run')")
    log(f"[reset] đã xoá dữ liệu ngày {d}")


def main():
    keys = {"gemini": os.environ.get("GEMINI_API_KEY", "").strip(), "groq": os.environ.get("GROQ_API_KEY", "").strip()}
    db = D1()
    if os.environ.get("RESET_TODAY") == "true":
        reset_today(db)
    last = db.get_state("last_run")
    if os.environ.get("TRIGGER") == "schedule" and last and \
            datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(minutes=15):
        log("[bỏ qua] lịch dự phòng: đã có lượt chạy trong 15 phút qua")
        return
    src = load_sources(db)
    now = datetime.now(timezone.utc)
    log(f"[nguồn] {len(src['telegram'])} nhóm, {len(src['website'])} trang web, {len(src['x'])} nguồn X, "
        f"{len(src['youtube'])} kênh YouTube, {len(src['sender'])} người theo dõi")
    health = Health(db.get_state("source_health", {}))

    # người theo dõi lấy từ database
    import filters
    filters._WATCH_SENDERS = set(filters._WATCH_SENDERS) | {str(r["value"]).lstrip("@").lower() for r in src["sender"]}

    # 1. Telegram
    min_ids = db.get_state("min_ids", {})
    msgs, info = ([], {})
    if src["telegram"]:
        msgs, info = asyncio.run(fetch_telegram(src["telegram"], min_ids, tg_creds()))
    per_group = defaultdict(int)
    for m in msgs:
        per_group[str(m["group_id"])] += 1
    for r in src["telegram"]:
        if str(r["value"]) in info:
            health.ok("telegram:" + str(r["value"]), per_group[str(r["value"])])
        else:
            health.fail("telegram:" + str(r["value"]), "not_joined")
    # cập nhật tên nhóm thật nếu người dùng chưa đặt tên
    for r in src["telegram"]:
        i = info.get(str(r["value"]))
        if i and not r.get("title"):
            db.query("UPDATE sources SET title = ? WHERE kind = 'telegram' AND value = ?", [i["real_title"], r["value"]])

    # 2. Trang web, tài khoản X và kênh YouTube (đều đọc qua RSS), bỏ bài đã lưu
    xmsgs = []
    has_feeds = bool(src["website"] or src["x"] or src["youtube"])
    if has_feeds:
        last_web = db.get_state("last_web_run")
        since = backfill_since() or (datetime.fromisoformat(last_web) - timedelta(hours=2) if last_web else start_of_today())
        wmsgs, _ = web_fetch.fetch([{"url": r["value"], "title": r.get("title")} for r in src["website"]], since,
                                   health=health)
        if src["x"]:
            xmsgs = x_fetch.fetch([r["value"] for r in src["x"]], since, log, health=health)
            log(f"[x] đọc {len(xmsgs)} bài")
            wmsgs += xmsgs
        if src["youtube"]:
            yt_cache = db.get_state("yt_ids", {})
            wmsgs += youtube_fetch.fetch([{"value": r["value"], "title": r.get("title")} for r in src["youtube"]],
                                         since, health, yt_cache, log)
            db.set_state("yt_ids", yt_cache)
        web_seen = db.get_state("web_seen", [])
        msgs += [m for m in wmsgs if m["uid"] not in set(web_seen)]
        web_seen = (web_seen + [m["uid"] for m in wmsgs if m["uid"] not in set(web_seen)])[-5000:]
    log(f"[đọc] {len(msgs)} tin mới")

    # Bỏ tin đã lưu ở lượt trước (khi lượt trước lỗi giữa chừng) để không đếm trùng
    uids = [m["uid"] for m in msgs]
    stored = set()
    for i in range(0, len(uids), 90):
        part = uids[i:i + 90]
        stored |= {r["uid"] for r in db.query(f"SELECT uid FROM messages WHERE uid IN ({','.join('?' * len(part))})", part)}
    if stored:
        log(f"[đọc] bỏ {len(stored)} tin đã xử lý ở lượt trước")
    msgs = [m for m in msgs if m["uid"] not in stored]  # dùng chung cho lọc và thống kê
    kept, stats = filter_messages(msgs)
    log(f"[lọc] {stats}")
    days = sorted({vn_day(m["date"]) for m in kept} | {datetime.now(VN).strftime("%Y-%m-%d")})
    today = datetime.now(VN).strftime("%Y-%m-%d")

    # 3. Token: CA mới + CA đã nhắc hôm nay (cập nhật giá)
    mentions = defaultdict(lambda: {"uids": set(), "groups": set(), "first": None, "links": []})
    for m in kept:
        for ca in m["contracts"]:
            x = mentions[(vn_day(m["date"]), ca)]  # token nhắc lúc 23:5x vẫn thuộc ngày đó
            x["uids"].add(m["uid"])
            x["from_x"] = x.get("from_x") or m.get("source") == "x"
            x["groups"].add(m["group"])
            if not x["first"] or m["date"] < x["first"]:
                x["first"], x["first_group"] = m["date"], m["group"]
                x["first_sender"] = m.get("sender_username") and "@" + m["sender_username"] or m.get("sender")
            if len(x["links"]) < 5:
                x["links"].append(m["link"])
    # CA chưa tra được ở lượt trước (DexScreener chưa ghi nhận token mới / lỗi mạng): tra lại trong 3 giờ
    pending = {ca: p for ca, p in db.get_state("ca_pending", {}).items()
               if now - datetime.fromisoformat(p["since"]) < timedelta(hours=3)}
    for ca, p in pending.items():
        x = mentions[(p["day"], ca)]
        x["uids"] |= set(p["uids"])
        x["groups"] |= set(p["groups"])
        x["from_x"] = x.get("from_x") or p.get("from_x")
        x["links"] = list(dict.fromkeys(p["links"] + x["links"]))[:5]
        if not x["first"] or p["first"] < x["first"]:
            x["first"], x["first_group"], x["first_sender"] = p["first"], p["first_group"], p["first_sender"]
    if os.environ.get("RECHECK_CA") == "true":  # chạy tay: quét lại CA trong tin đã lưu hôm nay mà chưa có trong bảng
        have = {r["address"] for r in db.query("SELECT address FROM token_days WHERE day = ?", [today])}
        from filters import extract_contracts
        n0 = len(mentions)
        for r in db.query("SELECT uid, date, data FROM messages WHERE day = ? ORDER BY date", [today]):
            d = json.loads(r["data"])
            for ca in extract_contracts(d.get("text") or ""):
                if ca in have:
                    continue
                x = mentions[(today, ca)]
                x["uids"].add(r["uid"])
                x["groups"].add(d.get("group") or "")
                if not x["first"] or r["date"] < x["first"]:
                    x["first"], x["first_group"] = r["date"], d.get("group")
                    x["first_sender"] = d.get("username") and "@" + d["username"] or d.get("sender")
                if len(x["links"]) < 5 and d.get("link"):
                    x["links"].append(d["link"])
        log(f"[token] quét lại tin hôm nay: {len(mentions) - n0} CA chưa có trong bảng")
    tok_days = sorted({d for d, _ in mentions} | {today})
    old = {(r["day"], r["address"]): json.loads(r["data"]) for r in db.query(
        f"SELECT day, address, data FROM token_days WHERE day IN ({','.join('?' * len(tok_days))})", tok_days)}
    pairs = list(dict.fromkeys(list(mentions) + [k for k in old if k[0] == today]))
    addrs_all = list(dict.fromkeys(ca for _, ca in pairs))
    dex = dexscreener.lookup(addrs_all) if addrs_all else {}
    found = dex or {}
    for (d, ca), x in mentions.items():  # CA chưa tra được: chờ lượt sau
        if ca in found:
            pending.pop(ca, None)
        else:
            p = pending.get(ca) or {"since": now.isoformat(), "day": d}
            p.update({"uids": sorted(x["uids"])[-20:], "groups": sorted(g for g in x["groups"] if g), "links": x["links"][:5],
                      "from_x": bool(x.get("from_x")), "first": x["first"], "first_group": x.get("first_group"),
                      "first_sender": x.get("first_sender")})
            pending[ca] = p
    db.set_state("ca_pending", dict(list(pending.items())[-100:]))
    if pending:
        log(f"[token] {len(pending)} CA chưa có trên DexScreener, sẽ tra lại ở lượt sau (tối đa 3 giờ)")
    if dex is None:  # DexScreener lỗi mạng: giữ nguyên CA trong tin, lượt sau cập nhật giá
        log("[token] DexScreener không trả lời, bỏ qua cập nhật token lượt này")
        dex = {}
    else:
        for m in kept:
            m["contracts"] = [c for c in m["contracts"] if c in dex]
    known = {}
    addrs = list(dex)
    for i in range(0, len(addrs), 90):
        part = [a.lower() if a.startswith("0x") else a for a in addrs[i:i + 90]]
        for r in db.query(f"SELECT * FROM tokens WHERE address IN ({','.join('?' * len(part))})", part):
            known[r["address"]] = r
    new_tokens, token_rows = [], []
    for day, ca in pairs:
        info_ = dex.get(ca)
        if not info_:
            continue
        key = ca.lower() if ca.startswith("0x") else ca
        prev = old.get((day, ca), {})
        mm = mentions.get((day, ca))
        uids = sorted(set(prev.get("uids", [])) | (mm["uids"] if mm else set()))
        t = {**info_,
             "uids": uids,
             "x": bool(prev.get("x") or (mm and mm.get("from_x"))),
             "mentions": len(uids) if uids else prev.get("mentions", 0),
             "groups": sorted(set(prev.get("groups", [])) | (mm["groups"] if mm else set())),
             "first_seen": prev.get("first_seen") or (mm["first"] if mm else None),
             "first_group": prev.get("first_group") or (mm.get("first_group") if mm else None),
             "first_sender": prev.get("first_sender") or (mm.get("first_sender") if mm else None),
             "msg_links": list(dict.fromkeys(prev.get("msg_links", []) + (mm["links"] if mm else [])))[:5]}
        k = known.get(key)
        if k and k.get("first_price") and t.get("price_usd"):
            t["base_price"], t["base_at"] = k["first_price"], k["first_at"]
            t["first_mention"] = k.get("first_mention")
            t["change_since_first"] = (t["price_usd"] / k["first_price"] - 1) * 100
        else:
            t["change_since_first"] = None
            if t.get("price_usd") and key not in {r[0] for r in new_tokens}:
                new_tokens.append([key, t["price_usd"], t["price_at"], t["first_seen"], t.get("symbol")])
        token_rows.append([day, ca, json.dumps(t, ensure_ascii=False)])
    db.upsert("tokens", ["address", "first_price", "first_at", "first_mention", "symbol"], new_tokens, conflict=["address"])
    db.upsert("token_days", ["day", "address", "data"], token_rows, conflict=["day", "address"])
    log(f"[token] {len(dex)} token, {len(new_tokens)} lần đầu")

    # 3b. Bài đăng X: lưu tất cả, tính lại trending của các ngày có bài mới
    new_x = [m for m in xmsgs if m["uid"] in {x["uid"] for x in msgs}]
    if new_x:
        from filters import extract_contracts
        db.upsert("x_posts", ["uid", "day", "date", "data"], [[m["uid"], vn_day(m["date"]), m["date"], json.dumps({
            "uid": m["uid"], "group": m["group"], "date": m["date"], "text": m["text"][:800], "link": m["link"],
            "contracts": [c for c in extract_contracts(m["text"]) if c in dex]}, ensure_ascii=False)] for m in new_x],
            conflict=["uid"])
        for d in sorted({vn_day(m["date"]) for m in new_x}):
            posts = [json.loads(r["data"]) for r in db.query("SELECT data FROM x_posts WHERE day = ?", [d])]
            db.upsert("x_trend", ["day", "data"], [[d, json.dumps(trending(posts), ensure_ascii=False)]], conflict=["day"])
        log(f"[x] {len(new_x)} bài mới")

    # 4. Lưu theo dõi, link (bảng messages ghi sau cùng, khi đã tóm tắt xong)
    db.upsert("watch", ["uid", "day", "date", "data"], [[m["uid"], vn_day(m["date"]), m["date"], json.dumps({
        "uid": m["uid"], "tags": m["watch"], "group": m["group"], "date": m["date"], "sender": m.get("sender"),
        "username": m.get("sender_username"), "text": m["text"][:1500], "links": m["links"][:5],
        "contracts": m["contracts"], "link": m["link"]}, ensure_ascii=False)] for m in kept if m["watch"]],
        conflict=["uid"])
    link_rows = {}
    skip = re.compile(r"^(?:https?://)?(?:[\w-]+\.)*(?:" + "|".join(map(re.escape, LINK_SKIP_DOMAINS)) + r")(?:[/:?#]|$)", re.I)
    for m in kept:
        for u in m["links"]:
            if skip.match(u):
                continue
            link_rows[(u, vn_day(m["date"]))] = [u, vn_day(m["date"]), m["date"], json.dumps({
                "url": u, "group": m["group"], "date": m["date"], "topics": m["topics"],
                "context": m["text"][:200], "msg": m["link"]}, ensure_ascii=False)]
    db.upsert("links", ["url", "day", "date", "data"], list(link_rows.values()), conflict=["url", "day"])

    # 4b. Bài báo có chủ đề: lấy toàn văn qua Jina Reader để AI tóm tắt sát hơn
    fulltext.enrich(kept, health, log)

    # 5. Tóm tắt theo giờ (gộp với phần đã có của giờ đó nếu lượt trước đã chạy)
    by_hour = defaultdict(list)
    for m in kept:
        if m["topics"]:
            by_hour[vn_hour(m["date"])].append(m)
    changed_days = set()
    fresh_by_day = defaultdict(list)  # sự kiện mới của lượt này, để nối vào bản tổng hợp khi chưa đến giờ AI gộp
    for h, ms in sorted(by_hour.items()):
        old = db.query("SELECT data FROM hours WHERE hour = ?", [h])
        o = json.loads(old[0]["data"]) if old else {}
        done = set(o.get("uids", []))
        ms = [m for m in ms if m["uid"] not in done]  # lượt trước lỗi giữa chừng: không tóm tắt lại
        if not ms:
            continue
        log(f"[AI] tóm tắt {h} ({len(ms)} tin)")
        res = sm.summarize(keys, ms, f"{h} (giờ Việt Nam), 60 phút")
        fresh_by_day[h[:10]] += res["events"]
        res = {"overview": (o.get("overview", "") + " " + res["overview"]).strip()[:1200],
               "events": o.get("events", []) + res["events"],
               "uids": sorted(done | {m["uid"] for m in ms})}
        res["count"] = len(res["uids"])
        changed_days.add(h[:10])
        db.upsert("hours", ["hour", "day", "data"], [[h, h[:10], json.dumps({"hour": h, "span": 1, **res},
                                                                             ensure_ascii=False)]], conflict=["hour"])

    # 6. Tổng hợp ngày: AI gộp lại tối đa mỗi giờ một lần (tiết kiệm hạn mức AI miễn phí).
    #    Lượt xen giữa chỉ nối sự kiện mới vào cuối bản tổng hợp; lượt AI gộp kế tiếp sẽ gộp trùng.
    merge_at = db.get_state("merge_at", {})
    pending = set(db.get_state("merge_pending", []))
    for d in sorted(changed_days | pending):
        old = db.query("SELECT data FROM digests WHERE day = ?", [d])
        last_m = merge_at.get(d)
        if old and last_m and now - datetime.fromisoformat(last_m) < timedelta(minutes=MERGE_EVERY_MIN):
            if fresh_by_day.get(d):
                digest = json.loads(old[0]["data"])
                digest["events"] = digest.get("events", []) + fresh_by_day[d]
                db.upsert("digests", ["day", "data", "updated_at"], [[d, json.dumps(digest, ensure_ascii=False),
                                                                      now.isoformat()]], conflict=["day"])
                log(f"[tổng hợp] nối {len(fresh_by_day[d])} sự kiện mới vào ngày {d}, AI gộp lại ở lượt sau")
            pending.add(d)
            continue
        hours = [json.loads(r["data"]) for r in db.query("SELECT data FROM hours WHERE day = ?", [d])]
        events = [e for h in hours for e in h.get("events", [])]
        pending.discard(d)
        if not events:
            continue
        log(f"[AI] tổng hợp ngày {d} ({len(events)} sự kiện)")
        digest = sm.merge_events(keys, events, f"ngày {d}")
        db.upsert("digests", ["day", "data", "updated_at"], [[d, json.dumps(digest, ensure_ascii=False),
                                                              now.isoformat()]], conflict=["day"])
        merge_at[d] = now.isoformat()
    keep = (datetime.now(VN) - timedelta(days=3)).strftime("%Y-%m-%d")
    db.set_state("merge_at", {k: v for k, v in merge_at.items() if k >= keep})
    db.set_state("merge_pending", sorted(d for d in pending if d >= keep))

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
    # Ghi tin đã xử lý (đánh dấu xong)
    db.upsert("messages", ["uid", "day", "date", "data"], [[m["uid"], vn_day(m["date"]), m["date"], json.dumps({
        "link": m["link"], "group": m["group"], "date": m["date"], "sender": m.get("sender"),
        "username": m.get("sender_username"), "text": m["text"][:400]},
        ensure_ascii=False)] for m in kept], conflict=["uid"])
    db.set_state("min_ids", min_ids)
    health.keep_only({f"{k}:{r['value']}" for k in ("telegram", "website", "x", "youtube") for r in src[k]})
    db.set_state("source_health", health.d)
    if has_feeds:
        db.set_state("web_seen", web_seen)
        db.set_state("last_web_run", now.isoformat())
    db.set_state("last_run", now.isoformat())

    # 8. Xoá dữ liệu cũ hơn 1 năm
    cutoff = (datetime.now(VN) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for t in ("hours", "digests", "messages", "watch", "links", "token_days", "stats", "x_posts", "x_trend"):
        db.query(f"DELETE FROM {t} WHERE day < ?", [cutoff])
    log("[xong]")


if __name__ == "__main__":
    main()
