"""Đọc tin nhắn nhóm bằng tài khoản cá nhân (Telethon), chế độ chỉ đọc, ẩn danh nhất có thể.

Những gì code này KHÔNG làm: gửi tin, thả cảm xúc, đánh dấu đã đọc, gõ phím, tải ảnh/file.
Người trong nhóm không nhìn thấy gì. Chỉ chủ tài khoản thấy thêm 1 phiên đăng nhập trong
Cài đặt > Thiết bị.
"""
import os
from datetime import datetime, timezone

from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityTextUrl


def _name(x):
    """Repo công khai: log trên GitHub ai cũng xem được, nên ẩn tên nhóm khi HIDE_NAMES=1."""
    return "(nhóm)" if os.environ.get("HIDE_NAMES") == "1" else x


def make_client(session_string, api_id, api_hash):
    return TelegramClient(
        StringSession(session_string), int(api_id), api_hash,
        receive_updates=False,   # không nhận cập nhật realtime, chỉ đọc lịch sử khi gọi
        flood_sleep_threshold=120,
    )


def _hidden_urls(msg):
    out = []
    for ent in msg.entities or []:
        if isinstance(ent, MessageEntityTextUrl) and ent.url:
            out.append(ent.url)
    return out


def _sender_name(msg):
    s = msg.sender
    if s is None:
        return None
    name = " ".join(x for x in [getattr(s, "first_name", None), getattr(s, "last_name", None)] if x)
    return name or getattr(s, "title", None) or getattr(s, "username", None)


async def fetch_async(client, group_ids, since: datetime, min_ids=None, limit_per_group=None):
    """Trả về (messages, groups_info, max_ids). min_ids: {group_id: id tin cuối đã lấy} để lấy tiếp."""
    min_ids = min_ids or {}
    messages, groups, max_ids = [], {}, {}
    await client(functions.account.UpdateStatusRequest(offline=True))
    print("[telegram] đang nạp danh sách nhóm...", flush=True)
    await client.get_dialogs(limit=None)  # nạp danh sách nhóm để tra được ID
    for gid in group_ids:
        try:
            entity = await client.get_entity(gid)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] Không mở được nhóm {_name(gid)}: {type(e).__name__}. Tài khoản phụ đã vào nhóm này chưa?")
            continue
        title = getattr(entity, "title", str(gid))
        groups[gid] = {"id": gid, "title": title, "username": getattr(entity, "username", None)}
        internal = str(gid).replace("-100", "", 1)
        count = 0
        kwargs = {"reverse": True}
        if min_ids.get(gid):
            kwargs["min_id"] = min_ids[gid]
        else:
            kwargs["offset_date"] = since
        async for m in client.iter_messages(entity, **kwargs):
            max_ids[gid] = max(max_ids.get(gid, 0), m.id)
            if m.action is not None:  # tin hệ thống (vào/rời nhóm...)
                continue
            text = m.message or ""
            urls = _hidden_urls(m)
            if not text and not urls:
                continue
            messages.append({
                "uid": f"{entity.id}-{m.id}",  # cố định qua các lần chạy
                "id": m.id,
                "group_id": gid,
                "group": title,
                "date": m.date.astimezone(timezone.utc).isoformat(),
                "sender": _sender_name(m),
                "sender_id": m.sender_id,
                "sender_username": getattr(m.sender, "username", None),
                "text": text,
                "urls": urls,
                "link": f"https://t.me/{entity.username}/{m.id}" if getattr(entity, "username", None)
                        else f"https://t.me/c/{internal}/{m.id}",
            })
            count += 1
            if count % 500 == 0:
                print(f"[telegram] {_name(title)}: đã đọc {count} tin...", flush=True)
            if limit_per_group and count >= limit_per_group:
                break
        print(f"[telegram] {_name(title)}: {count} tin")
    await client(functions.account.UpdateStatusRequest(offline=True))
    return messages, groups, max_ids
