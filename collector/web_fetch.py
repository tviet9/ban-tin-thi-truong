"""Đọc tin từ trang web qua RSS/Atom. Nhận link RSS, hoặc link trang chủ (tự tìm link RSS trong trang)."""
import hashlib
import os
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

UA = {"User-Agent": "Mozilla/5.0 (news-digest/0.1)", "Accept": "application/rss+xml, application/xml, text/xml, text/html"}
TAG_RE = re.compile(r"<[^>]+>")


def _n(x):
    return "(trang)" if os.environ.get("HIDE_NAMES") == "1" else x


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def _find_feed(page_url, body):
    text = body.decode("utf-8", errors="ignore")
    for m in re.finditer(r"<link[^>]+>", text, re.I):
        tag = m.group(0)
        if re.search(r"application/(rss|atom)\+xml", tag, re.I):
            href = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if href:
                return urljoin(page_url, html.unescape(href.group(1)))
    return None


def _date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(body):
    """Trả về (tên trang, [ {title, summary, link, date} ])."""
    root = ET.fromstring(body)
    items, title = [], None
    for el in root.iter():
        name = _local(el.tag)
        if name == "title" and title is None:
            title = _clean(el.text)
        if name not in ("item", "entry"):
            continue
        it = {"title": "", "summary": "", "link": "", "date": None, "author": ""}
        for ch in el:
            n = _local(ch.tag)
            if n == "title":
                it["title"] = _clean(ch.text)
            elif n in ("description", "summary", "content") and not it["summary"]:
                it["summary"] = _clean(ch.text)[:600]
            elif n == "link":
                it["link"] = ch.get("href") or (ch.text or "").strip()
            elif n in ("creator", "author") and not it["author"]:
                # RSS: <dc:creator>tên</dc:creator>; Atom: <author><name>tên</name></author>
                it["author"] = _clean(ch.text or "".join(x.text or "" for x in ch))
            elif n in ("pubdate", "published", "updated", "date") and not it["date"]:
                it["date"] = _date(ch.text)
        if not re.match(r"^https?://", it["link"] or "", re.I):
            it["link"] = ""  # bỏ link lạ (javascript:, data:...)
        if it["title"]:
            items.append(it)
    return title, items


def fetch(websites, since, site_offset=100, health=None, key_prefix="website:", timeout=25):
    """websites: [{"url": ..., "title": tuỳ chọn}]. Trả về (messages, sites_info).
    health: ghi trạng thái từng nguồn (khoá key_prefix + url), xem health.py."""
    messages, sites = [], []
    for i, w in enumerate(websites):
        url = w["url"] if w["url"].startswith("http") else "https://" + w["url"]
        hkey = key_prefix + w["url"]
        try:
            body, ctype = _get(url, timeout)
            if "html" in ctype.lower() and b"<rss" not in body[:500] and b"<feed" not in body[:500]:
                feed = _find_feed(url, body)
                if not feed:
                    print(f"[web] {_n(url)}: không tìm thấy RSS. Hãy nhập thẳng link RSS của trang.")
                    if health:
                        health.fail(hkey, "no_feed")
                    continue
                url = feed
                body, _ = _get(url, timeout)
            site_title, items = parse_feed(body)
        except Exception as e:  # noqa: BLE001
            print(f"[web] {_n(url)}: lỗi {type(e).__name__}")
            if health:
                health.fail_exc(hkey, e)
            continue
        name = w.get("title") or site_title or url
        sites.append({"url": w["url"], "feed": url, "title": name})
        n = 0
        for it in items:
            if it["date"] and it["date"] < since:
                continue
            key = w["url"] + "|" + (it["link"] or it["title"])
            uid = "w-" + hashlib.md5(key.encode()).hexdigest()[:12]  # cố định, không phụ thuộc thứ tự nguồn
            messages.append({
                "uid": uid, "id": uid, "group_id": f"web:{w['url']}", "group": name,
                "date": (it["date"] or datetime.now(timezone.utc)).isoformat(),
                "sender": it["author"] or None, "text": f"{it['title']}. {it['summary']}".strip(),
                "urls": [it["link"]] if it["link"] else [], "link": it["link"] or url, "source": "web", "raw_title": it["title"],
            })
            n += 1
        print(f"[web] {_n(name)}: {n} bài")
        if health:
            health.ok(hkey, n)
    return messages, sites
