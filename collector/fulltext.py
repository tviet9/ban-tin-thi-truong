"""Đọc toàn văn bài báo qua Jina Reader (r.jina.ai, miễn phí, không cần key) để AI tóm tắt sát hơn.

RSS chỉ có tiêu đề + vài câu mô tả; bài nào lấy được toàn văn thì thay phần mô tả bằng nội dung bài.
Không có key: Jina giới hạn khoảng 20 lượt/phút, nên mỗi lượt chỉ đọc vài bài mới nhất và nghỉ giữa các lần gọi.
"""
import re
import time
import urllib.request

JINA = "https://r.jina.ai/"
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_ANTIBOT = ("just a moment", "performing security verification", "requiring captcha", "access denied", "verify you are human")


def clean(md):
    """Markdown của Jina -> chữ thường: bỏ ảnh, giữ chữ của link, bỏ dòng menu ngắn."""
    body = md.split("Markdown Content:", 1)[-1]
    body = _LINK.sub(r"\1", _IMG.sub("", body))
    lines = [ln.strip(" #*>-|\t") for ln in body.splitlines()]
    lines = [ln for ln in lines if len(ln) > 40]  # bỏ menu, nút chia sẻ, chú thích ngắn
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def is_antibot(text):
    t = text[:4000].lower()
    return any(k in t for k in _ANTIBOT)


def read(url, timeout=25):
    req = urllib.request.Request(JINA + url, headers={"Accept": "text/plain", "X-Return-Format": "markdown",
                                                      "User-Agent": "Mozilla/5.0 (news-digest/0.1)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000).decode("utf-8", errors="ignore")


def enrich(msgs, health, log=print, limit=15, max_chars=2500, budget_s=150, pause_s=3.2, reader=None):
    """Thêm toàn văn cho tin từ báo (source == "web") có chủ đề. Trả về số bài lấy được."""
    reader = reader or read
    todo = sorted((m for m in msgs if m.get("source") == "web" and m.get("topics") and m.get("link", "").startswith("http")),
                  key=lambda m: m["date"], reverse=True)[:limit]
    if not todo:
        return 0
    start, got, fails = time.monotonic(), 0, 0
    for i, m in enumerate(todo):
        if time.monotonic() - start > budget_s or fails >= 3:  # Jina đang lỗi liên tục: dừng, lượt sau thử lại
            break
        if i:
            time.sleep(pause_s)
        try:
            text = clean(reader(m["link"]))
        except Exception as e:  # noqa: BLE001
            fails += 1
            health.fail_exc("svc:jina", e)
            continue
        if is_antibot(text):
            fails += 1
            health.fail("svc:jina", "blocked", "trang bắt xác minh")
            continue
        if len(text) < 300:  # không đọc được phần thân bài, giữ mô tả RSS
            continue
        title = m.get("raw_title") or m["text"].split(". ", 1)[0]
        m["text"] = f"{title}. {text[:max_chars]}"
        m["fulltext"] = True
        got += 1
    if got:
        health.ok("svc:jina", got)
    log(f"[toàn văn] {got}/{len(todo)} bài")
    return got
