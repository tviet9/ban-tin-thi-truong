"""Xem nhanh một trang web công khai từ máy GitHub: mã trả về, tiêu đề, các link và đường dẫn API xuất hiện trong trang.
Chạy: python scripts/peek.py <url>
"""
import re
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read(3_000_000).decode("utf-8", errors="ignore")
        print("HTTP", r.status, r.headers.get("Content-Type"))
except Exception as e:  # noqa: BLE001
    print("LỖI", type(e).__name__, str(e)[:200])
    sys.exit(0)
print("title:", (re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I) or [None, ""])[1].strip()[:200])
print("độ dài:", len(body))
hrefs = sorted(set(re.findall(r'href="([^"#]{2,200})"', body)))
print("links:", len(hrefs))
for h in hrefs[:80]:
    print("  ", h)
paths = sorted(set(re.findall(r'["\'`](/(?:api|v\d|token|tokens|chart|trade|bsc|sol|solana|base|eth)[\w/{}$:.-]{0,80})["\'`]', body)))
print("đường dẫn đáng chú ý:", paths[:80])
scripts = re.findall(r'<script[^>]+src="([^"]+)"', body)
print("script:", scripts[:20])
