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


def test_x_tidy():
    import x_fetch
    assert x_fetch.feed_path("list:123") == "i/lists/123" and x_fetch.feed_path("@cz") == "cz" and x_fetch.feed_path("https://a/b.xml") is None
    m = x_fetch._tidy({"text": "RT by @elonmusk: Hello $DOGE. tóm tắt", "raw_title": "RT by @elonmusk: Hello $DOGE",
                       "sender": "@SpaceX", "link": "https://nitter.kareem.one/SpaceX/status/9#m"})
    assert m["group"] == "X · @elonmusk" and m["text"] == "Hello $DOGE" and m["link"] == "https://x.com/SpaceX/status/9", m
    assert m["uid"].startswith("x-") and m["source"] == "x"
    print("x tidy OK")


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


def test_dex_one_by_one():
    """Mỗi CA một lần hỏi: token nhiều cặp không chiếm chỗ của CA khác (lỗi CA 12:19 ngày 26/11)."""
    asked = []
    big = "0x" + "b" * 40

    def fake_get(url, retries=3):
        addr = url.rsplit("/", 1)[-1]
        asked.append(addr)
        n = 30 if addr == big else 1
        return {"pairs": [{"baseToken": {"address": addr, "symbol": "T"}, "priceUsd": "1", "liquidity": {"usd": 1}}] * n}
    old = dexscreener._get
    dexscreener._get = fake_get
    dexscreener.time.sleep = lambda s: None
    try:
        out = dexscreener.lookup([big, EVM])
    finally:
        dexscreener._get = old
    assert asked == [big, EVM] and set(out) == {big, EVM}, (asked, list(out))
    print("dex one-by-one OK")


def test_rss_discover():
    """Trang không khai báo RSS (vneconomy.vn): thử đường dẫn hay gặp, nhận đúng /tin-moi.rss."""
    import web_fetch
    feed = b'<?xml version="1.0"?><rss><channel><title>T</title><item><title>A</title><link>https://a.vn/1</link></item></channel></rss>'
    tried = []

    def fake_get(url, timeout=25):
        tried.append(url)
        if url.endswith("/tin-moi.rss"):
            return feed, "application/rss+xml"
        if url.endswith(".rss") or url.endswith("/feed") or url.endswith("/rss") or url.endswith(".xml"):
            raise OSError("404")
        return b"<html><a href='/rss.html'>RSS</a></html>", "text/html"
    old = web_fetch._get
    web_fetch._get = fake_get
    try:
        msgs, sites = web_fetch.fetch([{"url": "https://vneconomy.vn/"}], since=None)
    finally:
        web_fetch._get = old
    assert sites and sites[0]["feed"] == "https://vneconomy.vn/tin-moi.rss" and len(msgs) == 1, (sites, tried)
    print("rss discover OK")


def test_health():
    import urllib.error
    from health import Health, classify
    assert classify(urllib.error.HTTPError("u", 429, "", {}, None))[0] == "rate_limited"
    assert classify(urllib.error.HTTPError("u", 403, "", {}, None))[0] == "blocked"
    assert classify(urllib.error.URLError("x"))[0] == "network"
    h = Health()
    h.ok("website:a", 3)
    h.fail("website:b", "not_found")
    h.ok("svc:jina", 1)
    h.keep_only({"website:a"})
    assert set(h.d) == {"website:a", "svc:jina"} and h.d["website:a"]["count"] == 3
    print("health OK")


def test_fulltext():
    import fulltext
    from health import Health
    body = "x " * 200
    md = ("Title: A\nURL Source: u\nMarkdown Content:\n![ảnh](i.png)\nMenu\n"
          f"Đoạn 1 của bài viết về [lãi suất](https://a) điều hành, {body}\nChia sẻ")
    assert "lãi suất điều hành" in fulltext.clean(md) and "Menu" not in fulltext.clean(md)
    msgs = [{"source": "web", "topics": ["kinh_te_vn"], "link": f"https://a/{i}", "date": f"2026-01-0{i}",
             "text": f"Tiêu đề {i}. mô tả", "raw_title": f"Tiêu đề {i}"} for i in range(1, 4)]
    msgs.append({"source": "telegram", "topics": ["crypto"], "link": "https://t.me/x", "date": "2026-01-09", "text": "tg"})
    h = Health()
    calls = []
    got = fulltext.enrich(msgs, h, log=lambda *_: None, pause_s=0, reader=lambda u: calls.append(u) or md)
    assert got == 3 and len(calls) == 3 and msgs[0]["text"].startswith("Tiêu đề 1. Đoạn 1") and msgs[3]["text"] == "tg"
    assert "ok_at" in h.d["svc:jina"]
    # trang bắt xác minh: không thay nội dung, ghi lỗi
    m2 = [dict(msgs[0], text="T. mô tả")]
    fulltext.enrich(m2, h, log=lambda *_: None, pause_s=0, reader=lambda u: "Just a moment... " + body * 3)
    assert m2[0]["text"] == "T. mô tả" and h.d["svc:jina"]["kind"] == "blocked"
    print("fulltext OK")


def test_youtube():
    from datetime import datetime, timezone
    import youtube_fetch as yt
    from health import Health
    assert yt.normalize("https://www.youtube.com/@KenhABC/videos") == "@KenhABC"
    assert yt.normalize("https://www.youtube.com/channel/UC" + "a" * 22) == "UC" + "a" * 22
    feed = ("<feed xmlns='http://www.w3.org/2005/Atom' xmlns:yt='http://www.youtube.com/xml/schemas/2015' "
            "xmlns:media='http://search.yahoo.com/mrss/'><title>Kênh A</title>"
            "<entry><yt:videoId>v1</yt:videoId><title>Nhận định thị trường</title>"
            "<link rel='alternate' href='https://www.youtube.com/watch?v=v1'/><author><name>A</name></author>"
            "<published>2026-11-25T10:00:00+00:00</published><media:group><media:description>Mô tả video</media:description>"
            "</media:group></entry><entry><yt:videoId>v0</yt:videoId><title>Cũ</title>"
            "<published>2020-01-01T00:00:00+00:00</published></entry></feed>").encode()
    name, items = yt.parse_feed(feed)
    assert name == "Kênh A" and items[0]["desc"] == "Mô tả video" and items[0]["author"] == "A"
    yt._get = lambda url, timeout=20: feed
    h = Health()
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    out = yt.fetch([{"value": "UC" + "b" * 22, "title": None}], since, h, {}, log=lambda *_: None, sub=lambda u: "VN-Index tăng")
    assert len(out) == 1 and out[0]["uid"] == "yt-v1" and out[0]["text"] == "Nhận định thị trường. VN-Index tăng"
    def blocked(u):
        raise RuntimeError("Sign in to confirm you're not a bot")
    out = yt.fetch([{"value": "UC" + "b" * 22, "title": None}], since, h, {}, log=lambda *_: None, sub=blocked)
    assert out[0]["text"] == "Nhận định thị trường. Mô tả video" and h.d["svc:yt_sub"]["kind"] == "blocked"
    print("youtube OK")


def test_nitter_fallback():
    import x_fetch
    from health import Health
    tried = []

    def fake_fetch(sites, since, site_offset=100, health=None, key_prefix="", timeout=25, discover_feed=True):
        url = sites[0]["url"]
        tried.append(url.split("/")[2])
        if "kareem" in url:
            health.fail(key_prefix + url, "rate_limited")
            return [], []
        health.ok(key_prefix + url, 1)
        return [{"uid": "w-1", "text": "Hello", "raw_title": "Hello", "link": "https://n/a/status/1#m", "sender": "@a"}], []
    old = x_fetch.web_fetch.fetch
    x_fetch.web_fetch.fetch = fake_fetch
    try:
        h = Health()
        out = x_fetch.fetch(["list:1"], None, log=lambda *_: None, health=h)
        assert len(out) == 1 and tried[:2] == ["nitter.kareem.one", "nitter.tiekoetter.com"], tried
        assert h.d["svc:nitter:nitter.kareem.one"]["kind"] == "rate_limited" and "ok_at" in h.d["x:list:1"]
        tried.clear()
        x_fetch.fetch(["list:1"], None, log=lambda *_: None, health=h)
        assert tried[0] == "nitter.tiekoetter.com", "máy lấy được gần nhất phải thử trước"
    finally:
        x_fetch.web_fetch.fetch = old
    print("nitter fallback OK")
    # máy chính mất kết nối lần đầu: thử lại 1 lần, không chuyển sang máy dự phòng
    calls = []

    def flaky(sites, since, site_offset=100, health=None, key_prefix="", timeout=25, discover_feed=True):
        url = sites[0]["url"]
        calls.append(url.split("/")[2])
        if len(calls) == 1:
            health.fail(key_prefix + url, "network")
            return [], []
        health.ok(key_prefix + url, 1)
        return [{"uid": "w-2", "text": "Hi", "raw_title": "Hi", "link": "https://n/a/status/2#m", "sender": "@a"}], []
    x_fetch.web_fetch.fetch = flaky
    try:
        h = Health()
        out = x_fetch.fetch(["list:1"], None, log=lambda *_: None, health=h)
    finally:
        x_fetch.web_fetch.fetch = old
    assert len(out) == 1 and calls[0] == calls[1], calls
    print("nitter retry OK")


if __name__ == "__main__":
    test_rss_discover()
    test_dex_one_by_one()
    test_health()
    test_fulltext()
    test_youtube()
    test_nitter_fallback()
    test_filters()
    test_dex_parse()
    test_rss()
    test_x_tidy()
    test_merge_keeps_dropped()
    test_dex_down()
