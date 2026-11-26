"""Kiểm tra kết nối từ máy chạy (GitHub Actions) tới các dịch vụ phụ. Chỉ đọc, không ghi database.
Chạy: python scripts/probe.py [@kênh_youtube]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))
import fulltext  # noqa: E402
import web_fetch  # noqa: E402
import x_fetch  # noqa: E402
import youtube_fetch as yt  # noqa: E402
from health import classify  # noqa: E402


def step(name, fn):
    t = time.monotonic()
    try:
        print(f"[OK]  {name}: {fn()} ({time.monotonic() - t:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[LỖI] {name}: {classify(e)} {str(e)[:120]} ({time.monotonic() - t:.1f}s)", flush=True)


step("Jina đọc bài báo", lambda: f"{len(fulltext.clean(fulltext.read('https://vnexpress.net/kinh-doanh')))} ký tự")
for h in x_fetch.NITTER_HOSTS:
    step(f"Nitter {h}", lambda h=h: f"{len(web_fetch.parse_feed(web_fetch._get(f'https://{h}/elonmusk/rss', 15)[0])[1])} bài")
ch = sys.argv[1] if len(sys.argv) > 1 else "@VTV24"
cid = {}
step("YouTube tìm ID kênh", lambda: yt.resolve(ch, cid))
if cid or yt.CID.match(ch):
    items = []
    step("YouTube RSS kênh", lambda: (items.extend(yt.parse_feed(yt._get(yt.FEED + yt.resolve(ch, cid)))[1]), f"{len(items)} video")[1])
    if items:
        step("YouTube phụ đề video mới nhất", lambda: f"{len(yt.transcript(items[0]['link']))} ký tự")
