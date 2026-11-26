# Daily Market

Tổng hợp tin từ các nhóm Telegram và trang báo (RSS), lọc theo chủ đề (Kinh tế trong nước, ngoài nước,
Chứng khoán, Crypto), tóm tắt bằng AI miễn phí (Groq, dự phòng Gemini), chấm mức quan trọng 1–5,
tra token (CA) trên DexScreener. Cập nhật mỗi 30 phút, lưu 1 năm.

## Cách chạy
| Phần | Ở đâu | File |
|---|---|---|
| Lấy tin + tóm tắt mỗi 30 phút | GitHub Actions | `.github/workflows/hourly.yml` → `collector/run_hourly.py` |
| Web + database | Cloudflare Workers + D1 | `worker/` (tự đưa lên khi đẩy code, `.github/workflows/deploy.yml`) |
| Lấy session Telegram | Google Colab | `scripts/build_notebook.py` tạo `demo_colab.ipynb` (chỉ đăng nhập) |

## Secrets cần có (Settings → Secrets and variables → Actions)
`TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `GROQ_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`SITE_PASSWORD` (mật khẩu vào web). Tuỳ chọn: `GEMINI_API_KEY`.

## Nguồn tin
Danh sách nhóm, trang báo, người theo dõi **không nằm trong code** (repo công khai). Thêm/xoá trên web,
mục **Cài đặt nguồn**. Log của GitHub Actions không in tên nhóm hay nội dung tin (`HIDE_NAMES=1`).

## Kiểm tra (không cần mạng)
```bash
python3 tests/test_offline.py
python3 tests/test_hourly.py /tmp/t.sqlite   # cần telethon
node tests/test_worker.mjs /tmp/t.sqlite /tmp/out.html
```
