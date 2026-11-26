"""Lọc tin nhắn: giữ tin thuộc chủ đề, trích link và địa chỉ contract (CA)."""
import re
import unicodedata

from config import TOPICS, WATCH, WATCH_SENDERS

URL_RE = re.compile(r"(?:https?://|www\.|t\.me/)[^\s<>\"')\]]+", re.I)
EVM_RE = re.compile(r"(?<![0-9a-zA-Z])0x[a-fA-F0-9]{40}(?![0-9a-zA-Z])")
# Solana / Tron / các chuỗi base58 32-44 ký tự. Lọc nhầm sẽ bị loại ở bước DexScreener.
B58_RE = re.compile(r"(?<![0-9A-Za-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![0-9A-Za-z])")
TON_RE = re.compile(r"(?<![0-9A-Za-z_-])[EU]Q[A-Za-z0-9_-]{46}(?![0-9A-Za-z_-])")

MIN_LEN = 25  # tin ngắn hơn và không có link/CA thì bỏ (kiểu "gm", "ok", "hóng")


def strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def _compile(words):
    if not words:
        return None
    alt = "|".join(re.escape(w.lower()) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w]){'(?:' + alt + ')'}(?![\w])", re.I)


_TOPIC_RE = {
    key: (_compile(t.get("keywords")), _compile(t.get("exact")))
    for key, t in TOPICS.items()
}


_WATCH_RE = {
    key: (_compile(t.get("keywords")), _compile(t.get("exact")))
    for key, t in WATCH.items()
}
_WATCH_SENDERS = {str(x).lstrip("@").strip().lower() for x in WATCH_SENDERS if str(x).strip()}


def _match(text, table):
    plain = strip_accents(text)
    lowered = unicodedata.normalize("NFC", text).lower()
    found = []
    for key, (kw_re, exact_re) in table.items():
        if (kw_re and kw_re.search(plain)) or (exact_re and exact_re.search(lowered)):
            found.append(key)
    return found


def topics_of(text: str):
    return _match(text, _TOPIC_RE)


def watch_tags(m):
    """Nhãn theo dõi của 1 tin: chain_moi, launchpad, nguoi (người gửi nằm trong WATCH_SENDERS)."""
    tags = _match(m.get("text") or "", _WATCH_RE)
    ids = {str(m.get("sender_id") or ""), (m.get("sender_username") or "").lower(), (m.get("sender") or "").strip().lower()}
    if _WATCH_SENDERS & (ids - {""}):
        tags.append("nguoi")
    if m.get("flow"):  # tin từ kênh Dòng tiền: luôn giữ, hiện ở mục Dòng tiền
        tags.append("dong_tien")
    return tags


TG_LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/", re.I)


def extract_links(text: str, extra_urls=()):
    """Link trong tin, đã bỏ link Telegram (t.me...) vì không cần tổng hợp."""
    links = [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]
    links += list(extra_urls)
    seen, out = set(), []
    for u in links:
        if TG_LINK_RE.match(u):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_contracts(text: str):
    """Trả về danh sách CA (giữ thứ tự, không trùng). Bỏ chuỗi nằm trong link không phải CA."""
    cas = EVM_RE.findall(text) + TON_RE.findall(text)
    for cand in B58_RE.findall(text):
        # chuỗi base58 thật thường có cả chữ và số, loại các từ toàn chữ
        if any(ch.isdigit() for ch in cand) and any(ch.isalpha() for ch in cand):
            cas.append(cand)
    seen, out = set(), []
    for ca in cas:
        key = ca.lower() if ca.startswith("0x") else ca
        if key not in seen:
            seen.add(key)
            out.append(ca)
    return out


def _fingerprint(text: str) -> str:
    return re.sub(r"\W+", " ", strip_accents(text)).strip()[:200]


def filter_messages(messages):
    """messages: list dict {id, group_id, group, date, sender, text, urls}.
    Trả về (kept, stats). kept có thêm topics, links, contracts."""
    kept, seen = [], set()
    stats = {"total": len(messages), "empty": 0, "short": 0, "off_topic": 0, "duplicate": 0}
    for m in messages:
        text = (m.get("text") or "").strip()
        links = extract_links(text, m.get("urls") or [])
        cas = extract_contracts(text + " " + " ".join(links))
        if not text and not links:
            stats["empty"] += 1
            continue
        watch = watch_tags({**m, "text": text})
        topics = topics_of(text)
        # Tin ngắn chỉ bị bỏ khi KHÔNG có từ khoá chủ đề (giữ lại kiểu "Fed giữ lãi suất", "BTC 98k")
        if len(text) < MIN_LEN and not links and not cas and not topics and not watch:
            stats["short"] += 1
            continue
        if cas and "crypto" not in topics:
            topics.append("crypto")
        if not topics and not watch:
            stats["off_topic"] += 1
            continue
        fp = _fingerprint(text)
        if fp and fp in seen and not cas and not watch:
            stats["duplicate"] += 1
            continue
        seen.add(fp)
        kept.append({**m, "text": text, "topics": topics, "links": links, "contracts": cas, "watch": watch})
    stats["kept"] = len(kept)
    stats["watch"] = sum(1 for m in kept if m["watch"])
    return kept, stats
