"""Đóng gói code thành notebook Google Colab: demo_colab.ipynb"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def writefile(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    return code(f"%%writefile /content/app/{rel}\n{src}")


cells = [
    md("""
# Bản tin Thị trường: chạy thử với dữ liệu thật

Notebook này đọc tin 3 nhóm Telegram trong 24 giờ qua, lọc theo chủ đề, tra token trên DexScreener,
tóm tắt bằng Gemini rồi xuất ra trang web `ban_tin.html`.

**Cách chạy:** bấm *Runtime → Run all* (Thời gian chạy → Chạy tất cả), rồi nhập thông tin khi được hỏi ở ô số 2 và số 3.

**Lưu ý:** notebook sẽ **dừng chờ** ở các ô hỏi thông tin. Nếu thấy chạy lâu, kéo xuống tìm ô có khung nhập chữ đang nhấp nháy,
nhập rồi bấm Enter. Thời gian chạy bình thường: đọc tin 1–3 phút, tóm tắt 3–8 phút.

**Bảo mật:**
- Mọi thứ chạy trong máy ảo Colab của riêng bạn. Không ai khác (kể cả Claude) thấy key, mã OTP hay tin nhắn.
- Key và mã OTP nhập qua ô ẩn, không lưu vào notebook.
- Code chỉ **đọc**: không gửi tin, không đánh dấu đã đọc, không hiện "đang online". Người trong nhóm không biết.
"""),
    md("## 1. Cài thư viện và nạp code"),
    code("!pip -q install telethon==1.36.0 qrcode[pil]\n!mkdir -p /content/app/collector /content/app/web"),
]
_local = ROOT / "sources_local.json"
if _local.exists():  # danh sách nhóm riêng tư: chỉ nằm trong notebook của bạn, không đưa lên GitHub
    cells.append(code("%%writefile /content/app/sources_local.json\n" + _local.read_text(encoding="utf-8")))
for rel in ["collector/config.py", "collector/filters.py", "collector/dexscreener.py", "collector/summarize.py",
            "collector/telegram_fetch.py", "collector/web_fetch.py", "collector/pipeline.py", "web/template.html"]:
    cells.append(writefile(rel))
cells += [
    md("""
## 2. Nhập key
- `api_id`, `api_hash`: lấy ở https://my.telegram.org → *API development tools*
- Gemini API key: lấy ở https://aistudio.google.com → *Get API key*
- Groq API key (dự phòng, miễn phí): https://console.groq.com → đăng nhập bằng Google → *API Keys* → *Create API Key*
"""),
    code("""
import sys, getpass
sys.path.insert(0, "/content/app/collector")
API_ID = input("api_id: ").strip()
API_HASH = getpass.getpass("api_hash (ẩn): ").strip()
GEMINI_KEY = getpass.getpass("Gemini API key (ẩn, bỏ trống nếu không có): ").strip()
GROQ_KEY = getpass.getpass("Groq API key - dự phòng khi Gemini hết hạn mức (ẩn, bỏ trống nếu không có): ").strip()
AI_KEYS = {"gemini": GEMINI_KEY, "groq": GROQ_KEY}
if not GEMINI_KEY and not GROQ_KEY:
    raise SystemExit("Cần ít nhất 1 key: Gemini hoặc Groq.")
print("Đã nhận key.")
"""),
    md("""
## 3. Đăng nhập Telegram
**Cách 1 (khuyên dùng): quét mã QR**, không cần mã OTP.
Trên điện thoại, mở app Telegram đang đăng nhập **tài khoản phụ** → **Cài đặt** → **Thiết bị** →
**Liên kết thiết bị máy tính** (Link Desktop Device) → quét mã QR hiện ở dưới. Sau đó nhập mật khẩu 2 bước nếu có.

**Cách 2:** nhập số điện thoại và mã OTP.

Nếu bạn đã có *session string* từ lần chạy trước, dán vào ô hỏi đầu tiên để khỏi nhập OTP.
"""),
    code("""
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram_fetch import make_client

saved = getpass.getpass("Session string cũ (bỏ trống nếu đăng nhập mới): ").strip()
client = make_client(saved, API_ID, API_HASH)
await client.connect()
if not await client.is_user_authorized():
    from telethon.errors import SessionPasswordNeededError
    method = input("Chọn cách đăng nhập: gõ 1 = quét QR (khuyên dùng), 2 = mã OTP: ").strip()
    if method != "2":
        import asyncio, qrcode
        from IPython.display import Image, display, clear_output
        # Đăng nhập QR cần nhận "cập nhật" từ Telegram, nên dùng một client tạm có bật cập nhật
        await client.disconnect()
        qc = TelegramClient(StringSession(), int(API_ID), API_HASH)
        await qc.connect()
        qr = await qc.qr_login()
        done = False
        for attempt in range(5):
            clear_output(wait=True)
            qrcode.make(qr.url).save("/content/qr.png")
            print("Điện thoại: Telegram (tài khoản phụ) > Cài đặt > Thiết bị > Liên kết thiết bị máy tính > quét mã này.")
            print(f"Mã hết hạn sau khoảng 30 giây, sẽ tự tạo mã mới (lần {attempt + 1}/5).")
            display(Image("/content/qr.png", width=260))
            print("Nếu bạn mở Colab ngay trên điện thoại (không quét được), thử bấm link này:", qr.url)
            try:
                await qr.wait(timeout=30)
                done = True
                break
            except asyncio.TimeoutError:
                await qr.recreate()
            except SessionPasswordNeededError:
                clear_output(wait=True)
                await qc.sign_in(password=getpass.getpass("Đã quét xong. Mật khẩu xác minh 2 bước (ẩn): "))
                done = True
                break
        clear_output(wait=True)
        if not done:
            await qc.disconnect()
            raise SystemExit("Hết 5 lần mà chưa quét được. Chạy lại ô này để thử tiếp.")
        tmp_session = qc.session.save()
        await qc.disconnect()
        client = make_client(tmp_session, API_ID, API_HASH)  # client chỉ đọc, không nhận cập nhật
        await client.connect()
    else:
        phone = input("Số điện thoại (dạng +849xxxxxxxx, bỏ số 0 đầu): ").strip().replace(" ", "")
        if phone.startswith("0"):
            phone = "+84" + phone[1:]
        print("Đang yêu cầu mã cho", phone[:5] + "*****" + phone[-2:])
        sent = await client.send_code_request(phone)
        kind = type(sent.type).__name__
        WHERE = {
            "SentCodeTypeApp": "trong APP TELEGRAM của tài khoản này (khung chat tên 'Telegram' có tích xanh), KHÔNG phải SMS",
            "SentCodeTypeSms": "qua TIN NHẮN SMS về số điện thoại",
            "SentCodeTypeCall": "qua CUỘC GỌI",
            "SentCodeTypeFlashCall": "qua CUỘC GỌI NHÁY (mã là các số cuối của số gọi đến)",
            "SentCodeTypeEmailCode": "qua EMAIL đã liên kết với tài khoản Telegram",
            "SentCodeTypeFragmentSms": "qua Fragment (số ảo)",
            "SentCodeTypeMissedCall": "qua CUỘC GỌI NHỠ (mã là các số cuối của số gọi đến)",
            "SentCodeTypeFirebaseSms": "qua TIN NHẮN SMS về số điện thoại",
            "SentCodeTypeSmsWord": "qua SMS (mã là một từ)",
            "SentCodeTypeSmsPhrase": "qua SMS (mã là một cụm từ)",
        }
        if kind == "SentCodeTypeSetUpEmailRequired":
            raise SystemExit("Telegram yêu cầu tài khoản này cài EMAIL ĐĂNG NHẬP trước. Mở app Telegram (tài khoản phụ) > "
                             "Cài đặt > Quyền riêng tư và bảo mật > Email đăng nhập, cài email, rồi chạy lại ô này.")
        print("Telegram đã gửi mã", WHERE.get(kind, kind))
        if kind != "SentCodeTypeApp":
            print("Lưu ý: Telegram chỉ gửi mã vào app khi tài khoản này ĐANG ĐĂNG NHẬP trên một app Telegram "
                  "(điện thoại/máy tính). Muốn nhận qua app: đăng nhập tài khoản phụ vào app trước, rồi chạy lại ô này.")
        HELP = ("Mở app Telegram > chuyển sang TÀI KHOẢN PHỤ > khung chat 'Telegram' (tích xanh) > tin mới nhất có 5 chữ số. "
                "Gõ mã vào đây. Nếu đợi quá 2 phút vẫn chưa có, gõ GUILAI (Telegram có thể đổi sang gửi SMS).")
        print(HELP)
        code = input("Mã OTP: ").strip()
        while code.upper() == "GUILAI":
            sent = await client.send_code_request(phone)
            print("Đã gửi lại:", WHERE.get(type(sent.type).__name__, type(sent.type).__name__))
            code = input("Mã OTP: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            await client.sign_in(password=getpass.getpass("Mật khẩu xác minh 2 bước (ẩn): "))
me = await client.get_me()
SESSION = client.session.save()
print("Đăng nhập thành công:", me.first_name)
"""),
    md("## 4. Đọc tin nhắn"),
    code("""
from datetime import datetime, timedelta, timezone
from config import GROUP_IDS
from telegram_fetch import fetch_async

HOURS_BACK = 24   # đổi thành 72 nếu muốn xem 3 ngày (tốn hạn mức Gemini hơn)
since = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
messages, groups, max_ids = await fetch_async(client, GROUP_IDS, since)
print(f"Tổng: {len(messages)} tin từ {len(groups)} nhóm")

import web_fetch
from config import WEBSITES
web_msgs, websites = web_fetch.fetch(WEBSITES, since) if WEBSITES else ([], [])
messages += web_msgs
if WEBSITES:
    print(f"Trang web: {len(web_msgs)} bài từ {len(websites)} trang")
"""),
    md("## 5. Lọc, tra token, tóm tắt (mất vài phút)"),
    code("""
import importlib, pipeline
importlib.reload(pipeline)
BUCKET_HOURS = 6   # gom 6 giờ / 1 lần gọi AI để tiết kiệm hạn mức miễn phí. Đặt 1 nếu muốn xem đúng từng giờ
data = pipeline.build(messages, groups, AI_KEYS, bucket_hours=BUCKET_HOURS,
                      history_path="/content/token_history.json", websites=websites)  # lưu giá lần đầu để tính % ở lần chạy sau
pipeline.render_html(data, "/content/ban_tin.html")
print("Xong. Tải file ban_tin.html ở ô dưới.")
"""),
    md("""## 6. Xem và tải kết quả
Ô dưới hiện trang kết quả **ngay trong Colab**. Muốn lưu file: bấm biểu tượng **thư mục** ở thanh bên trái →
`ban_tin.html` → dấu **⋮** → **Tải xuống**. (Nút tải tự động của Colab đôi khi treo ở "downloading".)"""),
    code("""
from IPython.display import HTML, display
display(HTML(open("/content/ban_tin.html", encoding="utf-8").read()))
"""),
    md("""
## 7. (Tuỳ chọn) Lưu session string cho bước chạy tự động
Session string **tương đương quyền đăng nhập tài khoản**. Chỉ lưu vào trình quản lý mật khẩu hoặc GitHub Secrets.
Không gửi cho ai, không dán vào chat.
"""),
    code("""
if input("Gõ HIEN để hiện session string: ").strip().upper() == "HIEN":
    print(SESSION)
"""),
    code("await client.disconnect()"),
]

nb = {"cells": cells, "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}
out = ROOT / "demo_colab.ipynb"
out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("->", out)
