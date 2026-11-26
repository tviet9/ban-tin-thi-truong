"""Tra giá, volume, thanh khoản, tuổi token trên DexScreener (API miễn phí, không cần key)."""
import json
import time
import urllib.request
from datetime import datetime, timezone

API = "https://api.dexscreener.com/latest/dex/tokens/"
# Tra TỪNG địa chỉ: API trả tối đa 30 cặp cho cả lần hỏi, hỏi chung nhiều CA thì token lớn (nhiều cặp)
# chiếm hết chỗ và CA mới bị coi là "không có trên DexScreener" (lỗi CA 12:19 ngày 26/11).


def _get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "news-digest/0.1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                print(f"[dexscreener] lỗi: {e}")
                return None
            time.sleep(2 * (i + 1))


def _age_text(created_ms):
    if not created_ms:
        return None, "?"
    hours = (time.time() * 1000 - created_ms) / 3_600_000
    if hours < 48:
        return hours, f"{hours:.0f} giờ"
    days = hours / 24
    if days < 60:
        return hours, f"{days:.0f} ngày"
    return hours, f"{days / 30:.0f} tháng"


def summarize_pairs(address, pairs):
    key = address.lower() if address.startswith("0x") else address
    own = [p for p in pairs if (p.get("baseToken", {}).get("address") or "").lower() == key.lower()]
    if not own:
        return None
    best = max(own, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    created = min((p.get("pairCreatedAt") or 10**15) for p in own)
    created = None if created == 10**15 else created
    hours, age = _age_text(created)
    bt = best.get("baseToken", {})
    return {
        "address": address,
        "symbol": bt.get("symbol"),
        "name": bt.get("name"),
        "chain": best.get("chainId"),
        "dex": best.get("dexId"),
        "price_usd": float(best["priceUsd"]) if best.get("priceUsd") else None,
        "change_24h": (best.get("priceChange") or {}).get("h24"),
        "price_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "volume_24h": sum(((p.get("volume") or {}).get("h24") or 0) for p in own),
        "liquidity_usd": sum(((p.get("liquidity") or {}).get("usd") or 0) for p in own),
        "fdv": best.get("fdv"),
        "market_cap": best.get("marketCap"),
        "age_hours": hours,
        "age": age,
        "created_at": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else None,
        "url": best.get("url"),
        "pairs": len(own),
    }


def lookup(addresses):
    """Trả về dict address -> thông tin (CA không có cặp giao dịch thì không có trong kết quả).
    Trả về None nếu không gọi được DexScreener."""
    out, fails, asked = {}, 0, 0
    for addr in dict.fromkeys(addresses):
        if asked:
            time.sleep(0.25)  # giới hạn 300 request/phút
        asked += 1
        data = _get(API + addr, retries=2)
        if data is None:
            fails += 1
            if fails >= 3 and not out:  # mất kết nối hẳn
                return None
            continue
        info = summarize_pairs(addr, data.get("pairs") or [])
        if info:
            out[addr] = info
    return None if asked and fails == asked else out
