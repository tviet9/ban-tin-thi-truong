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
# Bản tin Thị trường: tạo session string Telegram

Notebook này chỉ dùng để **đăng nhập tài khoản Telegram phụ và lấy session string** cho bản chạy tự động
(secret `TG_SESSION` trên GitHub). Việc lấy tin và tóm tắt đã chạy tự động mỗi giờ, không cần notebook.

**Cách chạy:** *Runtime → Run all*, nhập thông tin khi được hỏi, quét QR bằng điện thoại.
Mọi thứ chạy trong Colab của bạn; key, mã đăng nhập và session string không gửi đi đâu.
"""),
    code("!pip -q install telethon==1.36.0 qrcode[pil]\n!mkdir -p /content/app/collector"),
    writefile("collector/telegram_fetch.py"),
]
cells += [
    md("""
## 1. Nhập key
`api_id`, `api_hash`: lấy ở https://my.telegram.org → *API development tools*
"""),
    code("""
import sys, getpass
sys.path.insert(0, "/content/app/collector")
API_ID = input("api_id: ").strip()
API_HASH = getpass.getpass("api_hash (ẩn): ").strip()
print("Đã nhận key.")
"""),
    md("""
## 2. Đăng nhập Telegram
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
    md("""
## 3. Lấy session string (dán vào secret TG_SESSION trên GitHub)
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
