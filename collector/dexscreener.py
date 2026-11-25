"""Tra giá, volume, thanh khoản, tuổi token trên DexScreener (API miễn phí, không cần key)."""
import json
import time
import urllib.request
from datetime import datetime, timezone

API = "https://api.dexscreener.com/latest/dex/tokens/"
BATCH = 30  # API nhận tối đa 30 địa chỉ mỗi lần


def _get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "news-digest/0.1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                print(f"[dexscreener] lỗi: {e}")
                return {}
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
    """Trả về dict address -> thông tin. CA không có cặp giao dịch sẽ không có trong kết quả."""
    out = {}
    addresses = list(dict.fromkeys(addresses))
    for i in range(0, len(addresses), BATCH):
        chunk = addresses[i:i + BATCH]
        data = _get(API + ",".join(chunk))
        pairs = data.get("pairs") or []
        for addr in chunk:
            info = summarize_pairs(addr, pairs)
            if info:
                out[addr] = info
        time.sleep(0.4)  # giới hạn 300 request/phút
    return out
