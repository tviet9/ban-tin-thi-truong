"""Trạng thái từng nguồn (học từ Agent Reach): lần lấy được cuối, lỗi gần nhất, loại lỗi và gợi ý sửa.

Lưu trong bảng state, khoá "source_health": {khoá nguồn: {ok_at, count, err_at, kind, err}}.
Khoá nguồn: "telegram:<id>", "website:<url>", "x:<giá trị>", "youtube:<giá trị>",
dịch vụ phụ: "svc:nitter:<máy>", "svc:jina", "svc:yt_sub".
"""
import socket
import urllib.error
from datetime import datetime, timezone

# loại lỗi -> câu giải thích hiện trên web
KINDS = {
    "rate_limited": "Bị giới hạn lượt (429), thường tự hết sau vài giờ",
    "blocked": "Trang chặn máy chủ tự động (403/Cloudflare)",
    "not_found": "Không tìm thấy (404): link sai hoặc nguồn đã xoá",
    "network": "Không kết nối được (hết giờ chờ / máy chủ không trả lời)",
    "bad_feed": "Không đọc được nội dung (không phải RSS hợp lệ)",
    "no_feed": "Không tìm thấy RSS trong trang: hãy dán thẳng link RSS",
    "not_joined": "Không mở được nhóm: tài khoản phụ đã vào nhóm chưa?",
    "error": "Lỗi khác",
}


def classify(e):
    """Đổi exception thành (loại lỗi, mô tả ngắn)."""
    if isinstance(e, urllib.error.HTTPError):
        code = e.code
        kind = "rate_limited" if code == 429 else "blocked" if code in (401, 403, 503) else "not_found" if code in (404, 410) else "error"
        return kind, f"HTTP {code}"
    if isinstance(e, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError)):
        return "network", type(e).__name__
    if type(e).__name__ in ("ParseError", "ExpatError"):
        return "bad_feed", "XML lỗi"
    return "error", type(e).__name__


class Health:
    def __init__(self, prev=None):
        self.d = dict(prev or {})

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="minutes")

    def ok(self, key, count=None):
        e = self.d.setdefault(key, {})
        e["ok_at"] = self._now()
        e["count"] = count

    def fail(self, key, kind, detail=""):
        e = self.d.setdefault(key, {})
        e["err_at"] = self._now()
        e["kind"] = kind if kind in KINDS else "error"
        e["err"] = (KINDS[e["kind"]] + (f" ({detail})" if detail else ""))[:200]

    def fail_exc(self, key, exc):
        self.fail(key, *classify(exc))

    def last_ok(self, key):
        return (self.d.get(key) or {}).get("ok_at") or ""

    def keep_only(self, keys):
        """Bỏ trạng thái của nguồn đã xoá (dịch vụ phụ svc:* luôn giữ)."""
        self.d = {k: v for k, v in self.d.items() if k in keys or k.startswith("svc:")}
