"""Trending từ bài đăng X: hashtag, mã ($BTC), tài khoản được nhắc (@), từ khoá chủ đề."""
import re
import unicodedata
from collections import defaultdict

from filters import TOPICS, _compile, strip_accents

HASHTAG = re.compile(r"(?<!\w)#([A-Za-z0-9_À-ỹ]{2,40})")
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9]{1,14})\b")
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,15})")
_KW = {k: _compile(t.get("keywords")) for k, t in TOPICS.items()}
_SKIP = {"rt", "http", "https"}


def trending(posts, top=40):
    """posts: [{text, group, link}]. Trả về danh sách {term, kind, count, accounts, links} sắp theo số lần nhắc."""
    hits = defaultdict(lambda: {"count": 0, "accounts": set(), "links": []})

    def add(term, kind, p):
        h = hits[(kind, term.lower())]
        h.setdefault("term", term)
        h["count"] += 1
        h["accounts"].add(p.get("group") or "")
        if len(h["links"]) < 3 and p.get("link"):
            h["links"].append(p["link"])

    for p in posts:
        text = p.get("text") or ""
        seen = set()  # mỗi bài chỉ tính một lần cho mỗi từ
        found = [("$" + m.upper(), "Mã") for m in CASHTAG.findall(text)]
        found += [("#" + m, "Hashtag") for m in HASHTAG.findall(text)]
        found += [("@" + m, "Tài khoản") for m in MENTION.findall(text) if m.lower() not in _SKIP]
        nfc = unicodedata.normalize("NFC", text)
        plain = strip_accents(nfc)  # bỏ dấu giữ nguyên độ dài, nên vị trí khớp dùng lại được trên chữ gốc
        for topic, rx in _KW.items():
            if rx:
                for m in rx.finditer(plain):
                    kw = nfc[m.start():m.end()].strip().lower()  # hiện đúng chữ có dấu: "lãi suất"
                    if ("$" + strip_accents(kw).upper(), "Mã") not in found:
                        found.append((kw, "Từ khoá"))
        for term, kind in found:
            key = (kind, term.lower())
            if key in seen:
                continue
            seen.add(key)
            add(term, kind, p)
    out = [{"term": h["term"], "kind": k, "count": h["count"], "accounts": sorted(a for a in h["accounts"] if a),
            "links": h["links"]} for (k, t), h in hits.items()]
    out.sort(key=lambda x: (-x["count"], -len(x["accounts"]), x["term"]))
    return out[:top]
