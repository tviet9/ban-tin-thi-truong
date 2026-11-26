"""Đọc bài X qua Nitter (bản đọc X công khai có RSS), không cần tài khoản.

Nguồn X lưu trong database ở một trong các dạng:
  list:<id>   List X (x.com/i/lists/<id>)  -> đọc cả List một lần, ít bị chặn nhất
  @tên        một tài khoản               -> Nitter hay chặn khi đọc nhiều tài khoản lẻ (lỗi 429)
  https://... link RSS có sẵn (rss.app...)
"""
import hashlib
import re

import web_fetch

# Các máy Nitter công khai, thử lần lượt. shortcut: máy cộng đồng có thể ngừng bất cứ lúc nào, khi đó thêm máy khác vào đây.
NITTER_HOSTS = ["nitter.kareem.one", "nitter.tiekoetter.com"]
RT = re.compile(r"^RT by @(\w+):\s*")


def feed_path(value):
    v = value.strip()
    if v.startswith("list:"):
        return f"i/lists/{v[5:]}"
    if v.startswith("@"):
        return v[1:]
    return None


def _tidy(m):
    """Link về x.com, bài chia sẻ lại ghi cho người chia sẻ, mã tin cố định theo link X."""
    link = re.sub(r"^https?://[^/]+", "https://x.com", m["link"] or "").split("#")[0]
    title = m["text"].split(". ", 1)[0] if m.get("text") else ""
    who = (m.get("sender") or "").lstrip("@")
    rt = RT.match(m.get("raw_title") or title)
    if rt:
        who = rt.group(1)
    m["text"] = RT.sub("", m.get("raw_title") or m["text"]).strip() or m["text"]
    m["link"] = link
    m["urls"] = []
    m["uid"] = "x-" + hashlib.md5(link.encode()).hexdigest()[:12]
    m["group"] = "X · @" + who if who else "X"
    m["source"] = "x"
    return m


def fetch(values, since, log=print):
    """values: danh sách giá trị nguồn X. Trả về danh sách tin (đã chuẩn hoá)."""
    out = []
    for v in values:
        path = feed_path(v)
        if path is None:  # link RSS có sẵn
            got, _ = web_fetch.fetch([{"url": v, "title": "X"}], since)
        else:
            got = []
            for host in NITTER_HOSTS:
                got, _ = web_fetch.fetch([{"url": f"https://{host}/{path}/rss", "title": "X"}], since)
                if got:
                    break
            if not got:
                log("[x] không đọc được nguồn X lượt này (Nitter có thể đang chặn)")
        out += [_tidy(m) for m in got]
    seen, uniq = set(), []
    for m in out:
        if m["uid"] not in seen:
            seen.add(m["uid"])
            uniq.append(m)
    return uniq
