"""Tạo trang xem trước giao diện bằng dữ liệu mẫu (không cần mạng)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "collector"))
import test_offline, pipeline
data = test_offline.test_pipeline(str(ROOT / "tests" / "out_sample.html"))
ovs = {"08:00": "Số liệu CPI Mỹ thấp hơn dự báo, BTC vượt 98k, token MEOW được hô ở nhóm crypto.",
       "09:00": "VN-Index tăng phiên sáng, Binance niêm yết XYZ, NHNN công bố lịch họp báo 15h.",
       "10:00": "Tỷ giá trung tâm giảm, lợi suất trái phiếu Mỹ giảm, VN-Index đảo chiều cuối phiên."}
for h in data["hours"]:
    hh = h["hour"][11:]
    h["overview"] = ovs.get(hh, h["overview"])
    h["events"] = [e for e in data["digest"]["events"]
                   if pipeline._hour_key(data["messages"][e["source_ids"][0]]["date"])[11:] == hh]
for t in data["tokens"]:  # minh hoạ cột "Thay đổi": MEOW đã được nhắc ở lần cập nhật trước
    if t["symbol"] == "MEOW":
        t["base_price"], t["base_at"] = 0.000298, "2026-11-24T00:00:00+00:00"
        t["change_since_first"] = (t["price_usd"] / t["base_price"] - 1) * 100
    t["price_at"] = "2026-11-24T04:00:00+00:00"
data["generated_at"] = "2026-11-24T11:00+07:00"
data["sources"]["websites"] = [{"url": "https://vnexpress.net/rss/kinh-doanh.rss", "title": "VnExpress Kinh doanh (ví dụ)"}]
data["sources"]["watch_senders"] = ["nguoi_mau_1", "nguoi_mau_2"]
out = Path(sys.argv[1])
html = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
out.write_text(html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
print("preview ->", out)
