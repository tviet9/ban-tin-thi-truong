"""Đọc/ghi Cloudflare D1 qua REST API (dùng CLOUDFLARE_API_TOKEN có quyền D1 Edit)."""
import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
DB_NAME = os.environ.get("D1_NAME", "ban-tin")
MAX_PARAMS = 90  # D1 giới hạn 100 tham số mỗi câu lệnh


class D1:
    def __init__(self, account_id=None, token=None, db_name=DB_NAME):
        self.acc = account_id or os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.token = token or os.environ["CLOUDFLARE_API_TOKEN"]
        self.db = self._find_db(db_name)

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    out = json.loads(r.read().decode())
                if not out.get("success", True):
                    raise RuntimeError(f"D1 lỗi: {out.get('errors')}")
                return out
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="ignore")[:300]
                if e.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP {e.code}: {msg}") from e

    def _find_db(self, name):
        out = self._req("GET", f"/accounts/{self.acc}/d1/database?name={name}")
        for db in out.get("result", []):
            if db.get("name") == name:
                return db["uuid"]
        raise RuntimeError(f"Không thấy database D1 tên '{name}'. Chạy workflow Deploy trước.")

    def query(self, sql, params=None):
        out = self._req("POST", f"/accounts/{self.acc}/d1/database/{self.db}/query",
                        {"sql": sql, "params": list(params or [])})
        res = out.get("result") or []
        return res[0].get("results", []) if res else []

    def upsert(self, table, cols, rows, conflict=None):
        """INSERT nhiều dòng; conflict: tên cột khoá -> ghi đè các cột còn lại khi trùng."""
        rows = [list(r) for r in rows]
        if not rows:
            return
        per = max(1, MAX_PARAMS // len(cols))
        tail = ""
        if conflict:
            upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in conflict)
            tail = f" ON CONFLICT({', '.join(conflict)}) DO UPDATE SET {upd}" if upd else f" ON CONFLICT DO NOTHING"
        for i in range(0, len(rows), per):
            chunk = rows[i:i + per]
            ph = ", ".join("(" + ", ".join("?" * len(cols)) + ")" for _ in chunk)
            self.query(f"INSERT INTO {table} ({', '.join(cols)}) VALUES {ph}{tail}",
                       [v for r in chunk for v in r])

    def get_state(self, key, default=None):
        rows = self.query("SELECT value FROM state WHERE key = ?", [key])
        return json.loads(rows[0]["value"]) if rows else default

    def set_state(self, key, value):
        self.upsert("state", ["key", "value"], [[key, json.dumps(value, ensure_ascii=False)]], conflict=["key"])
