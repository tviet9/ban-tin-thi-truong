"""Kiểm tra không cần mạng: lọc tin, trích CA, DexScreener, đọc RSS, gộp sự kiện.
Chạy: python3 tests/test_offline.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

import dexscreener  # noqa: E402
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


def test_rss():
    import web_fetch
    rss = (b'<?xml version="1.0"?><rss><channel><title>Bao A</title>'
           b'<item><title>Fed &amp; l\xc3\xa3i su\xe1\xba\xa5t</title><description>&lt;p&gt;N\xe1\xbb\x99i dung&lt;/p&gt;</description>'
           b'<link>https://a.vn/1</link><pubDate>Tue, 24 Nov 2026 08:00:00 +0700</pubDate></item>'
           b'<item><title>Link xau</title><link>javascript:alert(1)</link></item></channel></rss>')
    name, items = web_fetch.parse_feed(rss)
    assert name == "Bao A" and items[0]["title"] == "Fed & lãi suất" and items[0]["summary"] == "Nội dung"
    assert items[0]["date"].isoformat() == "2026-11-24T08:00:00+07:00"
    assert items[1]["link"] == "", "link javascript: phải bị bỏ"
    _, items = web_fetch.parse_feed(b'<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>L</title>'
                                    b'<item><title>Hi</title><link>https://x.com/a/1</link><dc:creator>@elonmusk</dc:creator></item>'
                                    b'</channel></rss>')
    assert items[0]["author"] == "@elonmusk", items
    atom = (b'<feed xmlns="http://www.w3.org/2005/Atom"><title>B</title><entry><title>CPI</title>'
            b'<link href="https://b.com/x"/><updated>2026-11-24T01:00:00Z</updated></entry></feed>')
    _, items = web_fetch.parse_feed(atom)
    assert items[0]["link"] == "https://b.com/x" and items[0]["date"].tzinfo is not None
    assert web_fetch._find_feed("https://a.vn/", b'<link rel="alternate" type="application/rss+xml" href="/rss.xml">') == "https://a.vn/rss.xml"
    print("rss OK")


def test_merge_keeps_dropped():
    import summarize as sm
    events = [{"topic": "crypto", "title": f"E{i}", "points": ["x" * 400], "importance": 1 + i % 5,
               "source_ids": [str(i)]} for i in range(200)]
    sm.call = lambda keys, system, text: {"overview": "o", "events": [{"topic": "crypto", "title": "Gop", "points": [],
                                                                         "importance": 5, "source_ids": []}]}
    sm._DEAD.add(("gemini", "*"))  # chỉ còn Groq: giới hạn ngắn, buộc phải bỏ bớt
    out = sm.merge_events({"groq": "k"}, events, "ngày")
    assert len(out["events"]) > 150, "sự kiện không gửi được cho AI phải được giữ lại"
    assert sm._time_first("Fed giữ lãi suất (21:01)") == "21:01 · Fed giữ lãi suất"
    print("merge OK", len(out["events"]))


def test_dex_down():
    calls = []
    dexscreener._get = lambda url, retries=3: calls.append(url) or None
    assert dexscreener.lookup([EVM]) is None, "lỗi mạng phải trả None, không phải {}"
    print("dex-down OK")


if __name__ == "__main__":
    test_filters()
    test_dex_parse()
    test_rss()
    test_merge_keeps_dropped()
    test_dex_down()
