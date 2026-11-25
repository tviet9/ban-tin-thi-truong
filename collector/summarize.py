"""Tóm tắt bằng Google Gemini (gói miễn phí). Gọi REST trực tiếp, không cần cài SDK."""
import json
import re
import time
import urllib.error
import urllib.request

from config import (CUSTOM_INSTRUCTIONS, GEMINI_MODELS, GROQ_MAX_CHARS, GROQ_MODELS, IMPORTANCE_RULES,
                    MAX_CHARS_PER_CALL, SECTION_HINTS, SECTIONS, TAGS)

BASE = "https://generativelanguage.googleapis.com/v1beta"

EVENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "overview": {"type": "STRING"},
        "events": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "topic": {"type": "STRING", "enum": list(SECTIONS)},
                    "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": list(TAGS)}},
                    "title": {"type": "STRING"},
                    "points": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "importance": {"type": "INTEGER"},
                    "reason": {"type": "STRING"},
                    "source_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "contracts": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["topic", "title", "points", "importance", "source_ids"],
            },
        },
    },
    "required": ["overview", "events"],
}

SYSTEM = f"""Bạn là biên tập viên tin tài chính. Đầu vào là tin nhắn từ các nhóm Telegram tiếng Việt.
Nhiệm vụ:
1. Bỏ qua tin rác, tán gẫu, quảng cáo không có thông tin.
2. Gom các tin cùng nói về MỘT sự kiện thành một mục (event). Trường topic là đúng 1 trong các mục:
{SECTION_HINTS}
   Trường tags (có thể rỗng): "lai_suat" nếu liên quan lãi suất, "hop_bao" nếu là họp báo/phát biểu/AMA.
3. Mỗi event: title ngắn (dưới 15 từ), points là 1-5 gạch đầu dòng ý chính, importance 1-5 theo tiêu chí dưới,
   reason giải thích ngắn vì sao chấm điểm đó, source_ids là mã [..] của các tin gốc, contracts là CA được nhắc.
4. overview: 2-3 câu tóm tắt chung cả khung thời gian.
Tiêu chí importance:
{IMPORTANCE_RULES}
Định dạng mốc thời gian: mỗi gạch đầu dòng trong points BẮT ĐẦU bằng giờ của tin gốc (giờ Việt Nam, lấy từ tin) theo dạng
"HH:MM · nội dung", ví dụ "21:01 · Williams dự báo lạm phát giảm xuống 3,5%". Không ghi giờ trong ngoặc ở cuối câu.
Nếu tin khác ngày với phần lớn tin còn lại, ghi "dd/mm HH:MM · ".
Yêu cầu riêng:
{CUSTOM_INSTRUCTIONS}"""

MERGE_SYSTEM = SYSTEM + """
Đầu vào lần này là danh sách event đã tóm tắt từ nhiều phần. Gộp event trùng sự kiện, giữ đủ source_ids và contracts,
chấm lại importance, viết lại overview chung."""


class GeminiError(RuntimeError):
    pass


_NO_THINKING = {}  # model -> False nếu model không nhận cấu hình tắt "suy nghĩ"


def _post(model, api_key, system, user_text):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": EVENT_SCHEMA,
        },
    }
    # Tắt chế độ "suy nghĩ" của Gemini Flash: nhanh hơn nhiều lần, tóm tắt không cần suy luận sâu
    if _NO_THINKING.get(model, True):
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 400 and _NO_THINKING.get(model, True):
            msg = e.read().decode(errors="ignore")
            if "thinking" in msg.lower():
                _NO_THINKING[model] = False
                return _post(model, api_key, system, user_text)
            raise urllib.error.HTTPError(e.url, e.code, msg, e.headers, None) from e
        raise
    print(f"    [gemini] {model} trả lời sau {time.time() - t0:.0f}s", flush=True)
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise GeminiError(f"phản hồi lạ: {str(data)[:300]}") from e
    return _normalize(json.loads(text))


def _discover_models(api_key):
    """Khi các model cấu hình bị Google gỡ, tự tìm model 'flash' còn dùng được."""
    req = urllib.request.Request(f"{BASE}/models?pageSize=200", headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        models = json.loads(r.read().decode()).get("models", [])
    names = [m["name"].split("/", 1)[1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]
             and "image" not in m["name"] and "tts" not in m["name"]]
    return sorted(names, reverse=True)


_DISCOVERED = None
_DEAD = set()  # (provider, model) đã hết hạn mức trong ngày / không dùng được, bỏ qua cho các lần gọi sau


class TooLarge(GeminiError):
    """Không nhà cung cấp nào còn dùng được nhận nổi đoạn văn bản dài như vậy."""


def _quota_info(full):
    ids = re.findall(r'"quotaId":\s*"([^"]+)"', full)
    lim = re.findall(r"limit:\s*(\d+)", full)
    return f"quota={ids[:2]} limit={lim[:2]}" if ids or lim else full[:200]


def _call_gemini(api_key, system, user_text):
    if ("gemini", "*") in _DEAD:
        return None
    models = list(GEMINI_MODELS)
    tried_discovery = False
    i = 0
    while i < len(models):
        model = models[i]
        if ("gemini", model) in _DEAD:
            i += 1
            continue
        for attempt in range(4):
            try:
                return _post(model, api_key, system, user_text)
            except urllib.error.HTTPError as e:
                full = e.read().decode(errors="ignore") if e.fp else str(e.msg)
                if e.code == 429:
                    if "PerDay" in full or "per day" in full.lower():
                        print(f"[gemini] {model}: hết hạn mức miễn phí trong ngày ({_quota_info(full)}).", flush=True)
                        if re.search(r"limit:\s*0\b", full):
                            print("    -> limit 0: key Gemini này KHÔNG có hạn mức miễn phí. Bỏ qua Gemini, dùng Groq.", flush=True)
                            _DEAD.add(("gemini", "*"))
                            return None
                        _DEAD.add(("gemini", model))
                        break
                    m = re.search(r'"retryDelay":\s*"(\d+)', full)
                    wait = min(int(m.group(1)) + 2 if m else 20 * (attempt + 1), 65)
                    print(f"[gemini] {model} vượt hạn mức theo phút, chờ {wait}s ({attempt + 1}/4).", flush=True)
                    time.sleep(wait)
                    continue
                if e.code in (500, 503):
                    time.sleep(10)
                    continue
                if e.code in (400, 403) and "API key" in full:
                    raise GeminiError("API key Gemini sai hoặc chưa bật. Kiểm tra lại key ở aistudio.google.com") from e
                print(f"[gemini] {model} lỗi {e.code}: {full[:300]}")
                _DEAD.add(("gemini", model))
                break
            except (json.JSONDecodeError, GeminiError) as e:
                print(f"[gemini] {model} trả JSON lỗi, thử lại: {e}")
                time.sleep(3)
        i += 1
        if i == len(models) and not tried_discovery:
            tried_discovery = True
            global _DISCOVERED
            if _DISCOVERED is None:
                try:
                    _DISCOVERED = _discover_models(api_key)
                except Exception:  # noqa: BLE001
                    _DISCOVERED = []
            extra = [m for m in _DISCOVERED if m not in models and ("gemini", m) not in _DEAD][:2]
            if extra:
                print(f"[gemini] thử thêm model: {extra}")
                models += extra
    return None


JSON_SHAPE = """Trả về DUY NHẤT một object JSON đúng dạng:
{"overview": "...", "events": [{"topic": "kinh_te_vn|kinh_te_qt|chung_khoan|crypto", "tags": ["lai_suat", "hop_bao"], "title": "...",
 "points": ["..."], "importance": 1-5, "reason": "...", "source_ids": ["1-123"], "contracts": ["..."]}]}"""


def _normalize(out):
    """AI đôi khi trả sai cấu trúc: event là chuỗi, thiếu trường... Sửa về đúng dạng."""
    if not isinstance(out, dict):
        out = {"overview": "", "events": out if isinstance(out, list) else []}
    events = out.get("events")
    if not isinstance(events, list):
        events = []
    fixed = []
    for e in events:
        if isinstance(e, str):  # event dạng chuỗi trơn: thiếu thông tin, bỏ
            continue
        if not isinstance(e, dict) or not (e.get("title") or e.get("points")):
            continue
        pts = e.get("points")
        if isinstance(pts, str):
            pts = [pts]
        topic = e.get("topic")
        if topic not in SECTIONS:  # AI trả mục cũ/lạ: đoán gần đúng
            topic = {"chung_khoan": "chung_khoan", "crypto": "crypto"}.get(topic, "kinh_te_qt")
        tags = [t for t in (e.get("tags") or []) if t in TAGS] if isinstance(e.get("tags"), list) else []
        fixed.append({
            "topic": topic,
            "tags": tags,
            "title": str(e.get("title") or (pts[0] if pts else ""))[:200],
            "points": [str(x) for x in (pts or []) if x][:6],
            "importance": e.get("importance", 1),
            "reason": str(e.get("reason") or ""),
            "source_ids": [str(x) for x in (e.get("source_ids") or []) if x is not None] if isinstance(e.get("source_ids"), list) else [],
            "contracts": [str(x) for x in (e.get("contracts") or [])] if isinstance(e.get("contracts"), list) else [],
        })
    return {"overview": str(out.get("overview") or ""), "events": fixed}


_GROQ_DISCOVERED = None


def _groq_models(key, configured):
    global _GROQ_DISCOVERED
    if _GROQ_DISCOVERED is None:
        try:
            req = urllib.request.Request("https://api.groq.com/openai/v1/models",
                                         headers={"Authorization": f"Bearer {key}", "User-Agent": "news-digest/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                ids = [m["id"] for m in json.loads(r.read().decode()).get("data", []) if m.get("active", True)]
            bad = ("whisper", "tts", "guard", "compound", "orpheus", "playai", "prompt")
            _GROQ_DISCOVERED = [i for i in ids if not any(b in i.lower() for b in bad)]
        except Exception:  # noqa: BLE001
            _GROQ_DISCOVERED = []
    return [m for m in _GROQ_DISCOVERED if m not in configured]


def _call_openai_compat(name, url, key, models, max_chars, system, user_text):
    """Groq, OpenRouter... dùng chung chuẩn OpenAI."""
    models = list(models)
    discovered = False
    i = 0
    while i < len(models) or not discovered:
        if i >= len(models):
            discovered = True
            extra = _groq_models(key, models)[:3] if name == "groq" else []
            if not extra:
                break
            print(f"[{name}] thử thêm model: {extra}", flush=True)
            models += extra
            continue
        model = models[i]
        i += 1
        if (name, model) in _DEAD:
            continue
        for attempt in range(4):
            body = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": system + "\n" + JSON_SHAPE},
                                 {"role": "user", "content": user_text}]}
            if "gpt-oss" in model:
                body["reasoning_effort"] = "low"  # bớt token "suy nghĩ", đỡ tốn hạn mức theo phút
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "news-digest/0.1"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read().decode())
                out = _normalize(json.loads(data["choices"][0]["message"]["content"]))
                print(f"    [{name}] {model} trả lời sau {time.time() - t0:.0f}s", flush=True)
                return out
            except urllib.error.HTTPError as e:
                full = e.read().decode(errors="ignore") if e.fp else str(e.msg)
                if e.code == 429 or e.code == 413:
                    if e.code == 413 or "too large" in full.lower():
                        raise TooLarge(f"{name} {model}: đoạn quá dài") from e
                    if "per day" in full.lower() or "TPD" in full or "RPD" in full:
                        print(f"[{name}] {model}: hết hạn mức trong ngày.", flush=True)
                        _DEAD.add((name, model))
                        break
                    m = re.search(r"try again in ([\d.]+)s", full)
                    wait = min(int(float(m.group(1))) + 2 if m else 20 * (attempt + 1), 65)
                    print(f"[{name}] {model} vượt hạn mức theo phút, chờ {wait}s ({attempt + 1}/4).", flush=True)
                    time.sleep(wait)
                    continue
                if e.code in (401, 403):
                    raise GeminiError(f"Key {name} sai hoặc bị từ chối.") from e
                print(f"[{name}] {model} lỗi {e.code}: {full[:300]}")
                _DEAD.add((name, model))
                break
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"[{name}] {model} trả JSON lỗi, thử lại: {e}")
                time.sleep(3)
    return None


def call(keys, system, user_text):
    """keys: chuỗi (Gemini key) hoặc dict {"gemini": ..., "groq": ...}. Thử lần lượt từng nhà cung cấp."""
    if isinstance(keys, str):
        keys = {"gemini": keys}
    too_large = False
    if keys.get("gemini"):
        out = _call_gemini(keys["gemini"], system, user_text)
        if out is not None:
            return out
    if keys.get("groq"):
        if len(user_text) > GROQ_MAX_CHARS:
            too_large = True
        else:
            try:
                out = _call_openai_compat("groq", "https://api.groq.com/openai/v1/chat/completions",
                                          keys["groq"], GROQ_MODELS, GROQ_MAX_CHARS, system, user_text)
                if out is not None:
                    return out
            except TooLarge:
                too_large = True
    if too_large:
        raise TooLarge("Đoạn tin quá dài cho nhà cung cấp còn lại")
    raise GeminiError("Tất cả nhà cung cấp AI đều hết hạn mức hoặc lỗi. Xem các dòng log ở trên.")


def _vn_time(iso):
    from datetime import datetime, timedelta, timezone
    try:
        return datetime.fromisoformat(iso).astimezone(timezone(timedelta(hours=7))).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return iso[5:16] if iso else "?"


def _format(msgs):
    lines = []
    for m in msgs:
        t = _vn_time(m["date"])
        extra = ""
        if m.get("links"):
            extra += " | link: " + " ".join(m["links"][:3])
        lines.append(f"[{m['uid']}] {t} {m['group']} | {m.get('sender') or '?'}: {m['text'][:1500]}{extra}")
    return "\n".join(lines)


def _chunks(msgs):
    chunk, size = [], 0
    for m in msgs:
        line = len(m["text"][:1500]) + 120
        if chunk and size + line > MAX_CHARS_PER_CALL:
            yield chunk
            chunk, size = [], 0
        chunk.append(m)
        size += line
    if chunk:
        yield chunk


def _summarize_chunk(keys, msgs, label):
    try:
        return [call(keys, SYSTEM, f"Khung thời gian: {label}\nTin nhắn:\n{_format(msgs)}")]
    except TooLarge:
        if len(msgs) < 2:
            raise
        half = len(msgs) // 2
        print(f"    chia nhỏ {len(msgs)} tin thành 2 phần", flush=True)
        return _summarize_chunk(keys, msgs[:half], label) + _summarize_chunk(keys, msgs[half:], label)


_TAIL_TIME = re.compile(r"\s*\((?:lúc\s*)?(\d{1,2}/\d{1,2}\s+)?(\d{1,2}[:h]\d{2})\)\s*\.?$")
_HEAD_TIME = re.compile(r"^(\d{1,2}/\d{1,2}\s+)?\d{1,2}:\d{2}\s*[·\-–—:]\s*")


def _time_first(point):
    """Đưa mốc giờ ở cuối câu '(21:01)' lên đầu dòng '21:01 · ...' nếu AI quên làm."""
    p = str(point).strip()
    if _HEAD_TIME.match(p):
        return p
    m = _TAIL_TIME.search(p)
    if m:
        t = (m.group(1) or "") + m.group(2).replace("h", ":")
        return f"{t} · {p[:m.start()].rstrip()}"
    return p


def _clean(result):
    for e in result.get("events", []):
        try:
            e["importance"] = max(1, min(5, int(e.get("importance") or 1)))
        except (TypeError, ValueError):
            e["importance"] = 1
        e.setdefault("contracts", [])
        e.setdefault("reason", "")
        e.setdefault("points", [])
        e.setdefault("tags", [])
        e["points"] = [_time_first(p) for p in e["points"]]
        e["source_ids"] = [str(x) for x in e.get("source_ids") or []]
    result["events"].sort(key=lambda e: -e["importance"])
    return result


def _merge(keys, events, overviews, label):
    events = sorted((e for e in events if isinstance(e, dict)), key=lambda e: -(e.get("importance") or 0))
    slim = [{k: e.get(k) for k in ("topic", "tags", "title", "points", "importance", "source_ids", "contracts")}
            for e in events]
    gemini_alive = isinstance(keys, str) or (keys.get("gemini") and ("gemini", "*") not in _DEAD)
    limit = MAX_CHARS_PER_CALL if gemini_alive else GROQ_MAX_CHARS - 2000
    text = json.dumps(slim, ensure_ascii=False)
    while len(text) > limit and len(slim) > 1:  # quá dài: bỏ dần event ít quan trọng nhất
        slim.pop()
        text = json.dumps(slim, ensure_ascii=False)
    dropped = events[len(slim):]  # quá dài nên không gửi AI gộp: giữ nguyên, nối vào cuối
    try:
        out = call(keys, MERGE_SYSTEM, f"Khung thời gian: {label}\nEvents:\n{text}")
        out["events"] = list(out.get("events") or []) + dropped
        return out
    except TooLarge:  # không gộp được bằng AI: giữ nguyên các event
        print("    không gộp được bằng AI (quá dài), giữ nguyên danh sách", flush=True)
        return {"overview": " ".join(o for o in overviews if o)[:800], "events": events}


def summarize(keys, msgs, label):
    """msgs đã lọc (có uid). label: mô tả khung giờ. Trả về {overview, events}."""
    if not msgs:
        return {"overview": "Không có tin liên quan trong khung giờ này.", "events": []}
    parts = []
    for chunk in _chunks(msgs):
        parts += _summarize_chunk(keys, chunk, label)
    # Nhiều phần: nối lại, không gọi AI gộp (tiết kiệm hạn mức). Bản Tổng hợp cuối sẽ gộp trùng.
    result = {"overview": " ".join(p.get("overview", "") for p in parts if p.get("overview"))[:1200],
              "events": [e for p in parts for e in p.get("events", [])]}
    return _clean(result)


def merge_events(keys, events, label):
    """Gộp event của nhiều khung giờ thành bản tổng hợp cả kỳ."""
    if not events:
        return {"overview": "Chưa có dữ liệu.", "events": []}
    return _clean(_merge(keys, events, [], label))
