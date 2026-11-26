"""Kênh YouTube: video mới qua RSS của YouTube (không cần tài khoản), nội dung lấy từ phụ đề.

Giá trị nguồn: ID kênh (UC...), @tên_kênh hoặc link kênh.
Phụ đề lấy bằng yt-dlp (tiếng Việt, không có thì tiếng Anh). YouTube hay chặn máy chủ GitHub Actions
("xác nhận bạn không phải bot"): khi đó vẫn lấy tiêu đề + mô tả video, và trang Cài đặt nguồn báo lỗi phụ đề.
"""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from health import classify

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
      "Accept-Language": "vi,en;q=0.8"}
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="
CID = re.compile(r"^UC[\w-]{22}$")


def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read(5_000_000)


def normalize(value):
    """Link kênh / @tên / ID -> "UC..." hoặc "@tên"."""
    v = value.strip()
    m = re.search(r"(UC[\w-]{22})", v)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/(@[\w.-]+)", v) or re.match(r"^(@[\w.-]+)$", v)
    return m.group(1) if m else v


def resolve(value, cache):
    """Trả về ID kênh UC...; @tên thì mở trang kênh để tìm ID (lưu vào cache để lần sau khỏi mở)."""
    v = normalize(value)
    if CID.match(v):
        return v
    if v in cache:
        return cache[v]
    page = _get(f"https://www.youtube.com/{v}").decode("utf-8", errors="ignore")
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page) \
        or re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', page)
    if not m:
        raise LookupError("không thấy ID kênh")
    cache[v] = m.group(1)
    return cache[v]


def parse_feed(body):
    """RSS kênh -> (tên kênh, [ {id, title, link, date, desc, author} ])."""
    root = ET.fromstring(body)
    loc = lambda t: t.rsplit("}", 1)[-1]  # noqa: E731
    title = next((el.text for el in root if loc(el.tag) == "title"), "") or ""
    out = []
    for e in root:
        if loc(e.tag) != "entry":
            continue
        it = {"id": "", "title": "", "link": "", "date": None, "desc": "", "author": ""}
        for el in e.iter():
            n = loc(el.tag)
            if n == "videoId":
                it["id"] = el.text or ""
            elif n == "title" and not it["title"]:
                it["title"] = (el.text or "").strip()
            elif n == "link" and el.get("href"):
                it["link"] = el.get("href")
            elif n == "published":
                it["date"] = datetime.fromisoformat((el.text or "").replace("Z", "+00:00"))
            elif n == "description":
                it["desc"] = (el.text or "").strip()
            elif n == "name" and not it["author"]:
                it["author"] = (el.text or "").strip()
        if it["id"]:
            it["link"] = it["link"] or f"https://www.youtube.com/watch?v={it['id']}"
            out.append(it)
    return title.strip(), out


def _json3_text(body):
    data = json.loads(body)
    parts = ["".join(s.get("utf8", "") for s in ev.get("segs", [])) for ev in data.get("events", [])]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p.strip())).strip()


def transcript(video_url, langs=("vi", "vi-VN", "en")):
    """Phụ đề (có sẵn hoặc tự động) bằng yt-dlp, không tải video. Lỗi thì ném exception."""
    import yt_dlp  # nạp khi cần: chỉ dùng khi có nguồn YouTube
    opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    for pool in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang in langs:
            for key in (lang, lang + "-orig"):
                for f in pool.get(key) or []:
                    if f.get("ext") == "json3" and f.get("url"):
                        return _json3_text(_get(f["url"]))
    return ""


def fetch(sources, since, health, cache, log=print, max_subs=6, max_chars=6000, sub=None):
    """sources: [{"value", "title"}]. Trả về danh sách tin dạng giống tin báo."""
    sub = sub or transcript
    out, subs_done, sub_fail = [], 0, 0
    for s in sources:
        key = "youtube:" + s["value"]
        try:
            cid = resolve(s["value"], cache)
            name, items = parse_feed(_get(FEED + cid))
        except Exception as e:  # noqa: BLE001
            kind, detail = classify(e) if not isinstance(e, LookupError) else ("not_found", str(e))
            health.fail(key, kind, detail)
            log(f"[youtube] không đọc được kênh: {kind}")
            continue
        new = [it for it in items if it["date"] and it["date"] >= since]
        for it in new:
            body = it["desc"]
            if subs_done < max_subs and sub_fail < 2:  # YouTube chặn 2 lần liền thì thôi, lượt sau thử lại
                try:
                    t = sub(it["link"])
                    subs_done += 1
                    if t:
                        body = t
                        health.ok("svc:yt_sub", subs_done)
                except Exception as e:  # noqa: BLE001
                    sub_fail += 1
                    msg = str(e).lower()
                    if "bot" in msg or "sign in" in msg or "429" in msg:
                        health.fail("svc:yt_sub", "blocked", "YouTube đòi xác minh không phải bot")
                    else:
                        health.fail_exc("svc:yt_sub", e)
            out.append({
                "uid": "yt-" + it["id"], "id": it["id"], "group_id": key, "group": s.get("title") or name or "YouTube",
                "date": it["date"].astimezone(timezone.utc).isoformat(), "sender": it["author"] or None,
                "text": f"{it['title']}. {body}"[:max_chars], "urls": [], "link": it["link"],
                "source": "youtube", "raw_title": it["title"],
            })
        health.ok(key, len(new))
        log(f"[youtube] kênh: {len(new)} video mới")
    return out
