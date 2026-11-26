"""Đọc bài X qua Nitter (bản đọc X công khai có RSS), không cần tài khoản.

Nguồn X lưu trong database ở một trong các dạng:
  list:<id>   List X (x.com/i/lists/<id>)  -> đọc cả List một lần, ít bị chặn nhất
  @tên        một tài khoản               -> Nitter hay chặn khi đọc nhiều tài khoản lẻ (lỗi 429)
  https://... link RSS có sẵn (rss.app...)
"""
import hashlib
import re

import web_fetch

# Các máy Nitter công khai, thử lần lượt (máy lấy được gần nhất thử trước). Máy cộng đồng có thể ngừng bất cứ lúc
# nào: trạng thái từng máy hiện ở trang Cài đặt nguồn; thêm hoặc bớt máy ở danh sách này.
NITTER_HOSTS = ["nitter.kareem.one", "nitter.tiekoetter.com", "xcancel.com", "nitter.poast.org",
                "nitter.privacyredirect.com", "nitter.net", "nitter.space", "lightbrd.com"]
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


def host_order(health):
    """Máy lấy được gần nhất lên đầu; máy chưa từng lấy được giữ thứ tự gốc."""
    return sorted(NITTER_HOSTS, key=lambda h: health.last_ok("svc:nitter:" + h) if health else "", reverse=True)


def fetch(values, since, log=print, health=None):
    """values: danh sách giá trị nguồn X. Trả về danh sách tin (đã chuẩn hoá)."""
    from health import Health
    out = []
    for v in values:
        key = "x:" + v
        path = feed_path(v)
        if path is None:  # link RSS có sẵn
            got, _ = web_fetch.fetch([{"url": v, "title": "X"}], since, health=health, key_prefix="x:")
        else:
            got, ok, first_err = [], False, None
            for i, host in enumerate(host_order(health)):
                url = f"https://{host}/{path}/rss"
                # máy đầu tiên (lấy được gần nhất): chờ lâu hơn và thử lại 1 lần nếu mất kết nối
                for attempt in range(2 if i == 0 else 1):
                    tmp = Health()
                    got, _ = web_fetch.fetch([{"url": url, "title": "X"}], since, health=tmp, key_prefix="",
                                             timeout=30 if i == 0 else 15, discover_feed=False)
                    e = tmp.d.get(url, {})
                    if "ok_at" in e or e.get("kind") != "network":
                        break
                if "ok_at" in e and any("whitelist" in (m.get("text") or "").lower() for m in got):
                    e = {"kind": "blocked"}  # máy trả RSS nhưng chỉ có thông báo "chưa cho phép trình đọc RSS"
                    got = []
                if "ok_at" in e:
                    ok = True
                    if health:
                        health.ok("svc:nitter:" + host, len(got))
                    if got:
                        break
                    continue  # máy trả RSS rỗng: thử máy khác cho chắc
                if first_err is None:
                    first_err = (host, e)
                if health:
                    health.fail("svc:nitter:" + host, e.get("kind", "error"))
            if health:
                if ok:
                    health.ok(key, len(got))
                else:
                    h0, e0 = first_err or ("?", {})
                    health.fail(key, e0.get("kind", "error"), f"máy chính {h0} lỗi, các máy dự phòng cũng lỗi")
            if not ok:
                log("[x] không đọc được nguồn X lượt này (mọi máy Nitter đều lỗi)")
        out += [_tidy(m) for m in got]
    seen, uniq = set(), []
    for m in out:
        if m["uid"] not in seen:
            seen.add(m["uid"])
            uniq.append(m)
    return uniq
