"""Chạy toàn bộ pipeline với dữ liệu giả, không cần mạng: kiểm tra lọc, trích CA, gộp giờ, xuất HTML.
Chạy: python3 tests/test_offline.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

import dexscreener  # noqa: E402
import pipeline  # noqa: E402
import summarize as sm  # noqa: E402
from filters import extract_contracts, filter_messages, topics_of  # noqa: E402

EVM = "0x" + "a1" * 20
SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


def test_filters():
    assert topics_of("Fed giữ nguyên lãi suất") == ["lai_suat"]
    assert "crypto" not in topics_of("trong lòng tôi rất vui")          # 'lòng' không bị hiểu là 'long'
    assert "crypto" in topics_of("vào lệnh long BTC ở 97k")
    assert "kinh_te" in topics_of("giá vàng hôm nay tăng mạnh")
    assert "chung_khoan" in topics_of("VN-Index mất 12 điểm, khối ngoại bán ròng")
    assert extract_contracts(f"ca: {EVM} và {SOL}") == [EVM, SOL]
    assert extract_contracts("hello world https://example.com/abc") == []
    k, _ = filter_messages([{"uid": "x", "text": "Fed giữ lãi suất", "urls": [], "group": "G", "date": "2026-11-24T01:00:00+00:00", "link": "x"}])
    assert len(k) == 1, "tin ngắn có chủ đề phải được giữ"
    msgs = [
        {"uid": "1-1", "text": "gm", "urls": []},
        {"uid": "1-2", "text": "Tối nay đi ăn lẩu không anh em, quán quen ấy", "urls": []},
        {"uid": "1-3", "text": f"CA {SOL}", "urls": []},
        {"uid": "1-4", "text": "Fed giữ nguyên lãi suất 4.25-4.5%, Powell họp báo lúc 1h30", "urls": []},
        {"uid": "1-5", "text": "Fed giữ nguyên lãi suất 4.25-4.5%, Powell họp báo lúc 1h30", "urls": []},
    ]
    for m in msgs:
        m.update({"group": "G", "date": "2026-11-24T01:00:00+00:00", "link": "x"})
    kept, stats = filter_messages(msgs)
    assert [m["uid"] for m in kept] == ["1-3", "1-4"], kept
    assert stats == {"total": 5, "empty": 0, "short": 1, "off_topic": 1, "duplicate": 1, "kept": 2, "watch": 0}, stats
    import filters
    assert filters.watch_tags({"text": "Mainnet của chain mới ra mắt"}) == ["chain_moi"]
    assert filters.watch_tags({"text": "IDO trên launchpad, mở WL 20h"}) == ["launchpad"]
    filters._WATCH_SENDERS = {"minhtran", "12345"}
    assert filters.watch_tags({"text": "gm", "sender_username": "MinhTran"}) == ["nguoi"]
    assert filters.watch_tags({"text": "ok", "sender_id": 12345}) == ["nguoi"]
    filters._WATCH_SENDERS = set()
    print("filters OK", stats)


def test_dex_parse():
    pairs = [
        {"baseToken": {"address": EVM, "symbol": "AAA", "name": "A"}, "chainId": "bsc", "dexId": "pancakeswap",
         "priceUsd": "0.0012", "liquidity": {"usd": 50000}, "volume": {"h24": 1000}, "pairCreatedAt": 1, "url": "u1"},
        {"baseToken": {"address": EVM.upper().replace("0X", "0x"), "symbol": "AAA"}, "chainId": "bsc", "dexId": "x",
         "priceUsd": "0.0013", "liquidity": {"usd": 90000}, "volume": {"h24": 500}, "pairCreatedAt": 5, "url": "u2"},
        {"baseToken": {"address": "0xother"}, "quoteToken": {"address": EVM}, "liquidity": {"usd": 10**9}},
    ]
    info = dexscreener.summarize_pairs(EVM, pairs)
    assert info["url"] == "u2" and info["liquidity_usd"] == 140000 and info["volume_24h"] == 1500 and info["pairs"] == 2
    print("dexscreener parse OK")


def test_pipeline(out):
    raw = json.loads((ROOT / "tests" / "sample_messages.json").read_text(encoding="utf-8"))
    fake_dex = json.loads((ROOT / "tests" / "sample_dex.json").read_text(encoding="utf-8"))
    dexscreener.lookup = lambda addrs: {a: fake_dex[a] for a in addrs if a in fake_dex}
    calls = []

    def fake_call(key, system, text):
        calls.append(text)
        ids = [line[1:line.index("]")] for line in text.splitlines() if line.startswith("[")]
        if "Events:" in text:
            return json.loads((ROOT / "tests" / "sample_digest.json").read_text(encoding="utf-8"))
        return {"overview": f"{len(ids)} tin liên quan.", "events": [
            {"topic": "crypto", "title": "Sự kiện thử", "points": ["ý 1"], "importance": 3, "source_ids": ids[:3]}]}

    sm.call = fake_call
    import filters
    filters._WATCH_SENDERS = {"admin_vimo"}
    raw_groups = {i: {"title": t} for i, t in enumerate(sorted({m["group"] for m in raw["messages"]}))}
    data = pipeline.build(raw["messages"], raw_groups, "fake-key")
    data["sample"] = True
    assert data["tokens"] and data["hours"] and data["digest"]["events"] and data["watch"]
    assert all(m["uid"] in data["messages"] for m in data["watch"])
    pipeline.render_html(data, out)
    print(f"pipeline OK: {len(calls)} lần gọi AI, {len(data['tokens'])} token, xuất {out}")
    return data


if __name__ == "__main__":
    test_filters()
    test_dex_parse()
    test_pipeline(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "tests" / "out_sample.html"))
