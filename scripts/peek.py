"""Xem nhanh trang web công khai từ máy GitHub: mã trả về, tiêu đề, link RSS; một link thì in thêm link và đường dẫn API.
Chạy: python scripts/peek.py "<url> [url2 ...]"
"""
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}


def peek(url, full):
    print("=====", url)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            body = r.read(3_000_000).decode("utf-8", errors="ignore")
            print("HTTP", r.status, r.headers.get("Content-Type"), "->", r.geturl())
    except Exception as e:  # noqa: BLE001
        print("LỖI", type(e).__name__, str(e)[:200])
        return
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    print("title:", title.group(1).strip()[:200] if title else "")
    print("độ dài:", len(body), "| là RSS:", "<rss" in body[:2000] or "<feed" in body[:2000])
    rss = sorted(set(re.findall(r"""["']([^"'\s]*(?:rss|feed)[^"'\s]*)["']""", body, re.I)))
    print("link có chữ rss/feed:", rss[:40])
    if not full:
        return
    hrefs = sorted(set(re.findall(r'href="([^"#]{2,200})"', body)))
    print("links:", len(hrefs))
    for h in hrefs[:80]:
        print("  ", h)
    paths = sorted(set(re.findall(r"""["'`](/(?:api|v\d|token|tokens|chart|trade|bsc|sol|solana|base|eth)[\w/{}$:.-]{0,80})["'`]""", body)))
    print("đường dẫn đáng chú ý:", paths[:80])
    print("đoạn quanh /token/:", [body[max(0, m.start() - 80):m.start() + 80] for m in re.finditer(r"/token/", body)][:5])


urls = " ".join(sys.argv[1:]).split()
for u in urls:
    peek(u, full=len(urls) == 1)
