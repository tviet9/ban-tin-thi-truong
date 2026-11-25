"""Ghép các bước: lọc -> tra CA -> tóm tắt theo giờ -> tổng hợp ngày -> xuất dữ liệu cho web."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dexscreener
import summarize as sm
from config import SECTIONS, TAGS, TOPICS, WATCH, WATCH_SENDERS
from filters import filter_messages

VN = timezone(timedelta(hours=7))
TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "template.html"


def _hour_key(iso, bucket=1):
    d = datetime.fromisoformat(iso).astimezone(VN)
    return d.replace(hour=d.hour - d.hour % bucket).strftime("%Y-%m-%d %H:00")


def _apply_history(tokens, history_path):
    """% thay đổi chỉ tính khi CA đã được nhắc ở lần chạy TRƯỚC (có giá lưu lại). CA mới: ghi giá hiện tại làm mốc."""
    hist = {}
    if history_path and Path(history_path).exists():
        try:
            hist = json.loads(Path(history_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            hist = {}
    for t in tokens:
        key = t["address"].lower() if t["address"].startswith("0x") else t["address"]
        base = hist.get(key)
        if base and base.get("price") and t.get("price_usd"):
            t["base_price"] = base["price"]
            t["base_at"] = base["at"]
            t["first_mention"] = base.get("first_mention")
            t["change_since_first"] = (t["price_usd"] / base["price"] - 1) * 100
        else:
            t["change_since_first"] = None
            if t.get("price_usd"):
                hist[key] = {"price": t["price_usd"], "at": t.get("price_at"),
                             "first_mention": t.get("first_seen"), "symbol": t.get("symbol")}
    if history_path:
        Path(history_path).write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")


def build(raw_messages, groups, gemini_key, log=print, bucket_hours=1, history_path=None, websites=None):
    """gemini_key: chuỗi key Gemini, hoặc dict {"gemini": ..., "groq": ...}."""
    """bucket_hours: gom bao nhiêu giờ vào 1 lần tóm tắt. Demo 24h dùng 3 cho nhanh; chạy tự động dùng 1."""
    import time
    t_start = time.time()
    kept, stats = filter_messages(raw_messages)
    log(f"[lọc] {stats}")

    # Tra CA
    mentions = defaultdict(lambda: {"count": 0, "groups": set(), "first_seen": None, "msg_links": []})
    for m in kept:
        for ca in m["contracts"]:
            x = mentions[ca]
            x["count"] += 1
            x["groups"].add(m["group"])
            x["first_seen"] = min(filter(None, [x["first_seen"], m["date"]]))
            if len(x["msg_links"]) < 5:
                x["msg_links"].append(m["link"])
    log(f"[CA] {len(mentions)} địa chỉ nghi là CA, đang tra DexScreener...")
    dex = dexscreener.lookup(list(mentions)) if mentions else {}
    tokens = []
    for ca, info in dex.items():
        mm = mentions[ca]
        tokens.append({**info, "mentions": mm["count"], "groups": sorted(mm["groups"]),
                       "first_seen": mm["first_seen"], "msg_links": mm["msg_links"]})
    tokens.sort(key=lambda t: (-t["mentions"], -(t["liquidity_usd"] or 0)))
    _apply_history(tokens, history_path)
    valid_ca = set(dex)
    for m in kept:  # bỏ chuỗi không phải CA thật
        m["contracts"] = [c for c in m["contracts"] if c in valid_ca]
    log(f"[CA] {len(tokens)} token có cặp giao dịch")

    # Tóm tắt theo giờ
    by_hour = defaultdict(list)
    for m in kept:
        if m["topics"]:  # tin chỉ có nhãn theo dõi (không thuộc chủ đề) thì không đưa vào AI
            by_hour[_hour_key(m["date"], bucket_hours)].append(m)
    hours = []
    for h in sorted(by_hour):
        log(f"[AI] {len(hours) + 1}/{len(by_hour)}: tóm tắt {h} ({len(by_hour[h])} tin) · đã chạy {time.time() - t_start:.0f}s")
        res = sm.summarize(gemini_key, by_hour[h], f"{h} (giờ Việt Nam), {bucket_hours * 60} phút")
        hours.append({"hour": h, "span": bucket_hours, "count": len(by_hour[h]), **res})

    all_events = [e for h in hours for e in h["events"]]
    log("[AI] tổng hợp cả kỳ")
    first, last = (min(by_hour), max(by_hour)) if by_hour else ("", "")
    digest = sm.merge_events(gemini_key, all_events, f"{first} đến {last}")

    # Link quan trọng
    links = []
    seen = set()
    for m in kept:
        for u in m["links"]:
            if u in seen:
                continue
            seen.add(u)
            links.append({"url": u, "group": m["group"], "date": m["date"], "topics": m["topics"],
                          "context": m["text"][:200], "msg": m["link"]})

    watch_list = [{"uid": m["uid"], "tags": m["watch"], "group": m["group"], "date": m["date"],
                   "sender": m.get("sender"), "username": m.get("sender_username"), "text": m["text"][:1500],
                   "links": m["links"][:5], "contracts": m["contracts"], "link": m["link"]}
                  for m in kept if m["watch"]]
    watch_list.sort(key=lambda x: x["date"], reverse=True)

    messages_index = {m["uid"]: {"link": m["link"], "group": m["group"], "date": m["date"],
                                 "sender": m.get("sender"), "text": m["text"][:400]} for m in kept}
    return {
        "generated_at": datetime.now(VN).isoformat(timespec="minutes"),
        "sample": False,
        "topics": {k: v["label"] for k, v in TOPICS.items()},
        "sections": SECTIONS,
        "tags": TAGS,
        "groups": [g["title"] for g in groups.values()],
        "stats": stats,
        "digest": digest,
        "hours": list(reversed(hours)),
        "tokens": tokens,
        "links": links[-300:][::-1],
        "watch_labels": {**{k: v["label"] for k, v in WATCH.items()}, "nguoi": "Người theo dõi"},
        "watch": watch_list[:500],
        "sources": {
            "telegram": [{"id": g.get("id"), "title": g.get("title")} for g in groups.values()],
            "websites": [{"url": w.get("url"), "title": w.get("title")} for w in (websites or [])],
            "watch_senders": [str(x) for x in WATCH_SENDERS],
        },
        "api": False,  # True khi chạy trên web thật (Cloudflare): trang Cài đặt mới lưu được
        "messages": messages_index,
    }


def render_html(data, out_path):
    html = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload)
    html = ('<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '</head><body>\n' + html + '\n</body></html>')
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path
