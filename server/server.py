"""雙分化訓練 app 的同步伺服器（只用 Python 標準庫）

環境變數：
  GYM_TOKEN   必填，同步密碼（app 裡輸入同一個）
  GYM_DB      資料庫路徑，預設 ./gym.db
  GYM_PORT    監聽端口，預設 8787
  GYM_HOST    監聽地址，預設 127.0.0.1（由 Caddy / Cloudflare Tunnel 轉發）
  GYM_ORIGIN  允許的網頁來源，預設 https://hingaa4.github.io

API：
  GET  /api/health                 → {"ok": true}
  POST /api/sync  (Bearer token)   body: {"logs": [...], "prefs": {...}}
                                   → 合併後的 {"logs": [...], "prefs": {...}}
  每條 log 以 id 識別，u（更新時間 ms）較大的版本勝出；刪除用 del: true 標記。
"""
import hmac
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("GYM_TOKEN", "")
DB_PATH = os.environ.get("GYM_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym.db"))
PORT = int(os.environ.get("GYM_PORT", "8787"))
HOST = os.environ.get("GYM_HOST", "127.0.0.1")
ORIGIN = os.environ.get("GYM_ORIGIN", "https://hingaa4.github.io")
MAX_BODY = 5 * 1024 * 1024

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS logs (id TEXT PRIMARY KEY, u INTEGER NOT NULL, data TEXT NOT NULL)")
db.execute("CREATE TABLE IF NOT EXISTS prefs (k TEXT PRIMARY KEY, u INTEGER NOT NULL, data TEXT NOT NULL)")
db.commit()
lock = threading.Lock()


def merge(payload: dict) -> dict:
    with lock:
        for log in payload.get("logs") or []:
            if not isinstance(log, dict) or not isinstance(log.get("id"), str):
                continue
            u = int(log.get("u") or 0)
            db.execute(
                "INSERT INTO logs (id, u, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET u=excluded.u, data=excluded.data WHERE excluded.u > logs.u",
                (log["id"], u, json.dumps(log, ensure_ascii=False)),
            )
        prefs = payload.get("prefs")
        if isinstance(prefs, dict):
            db.execute(
                "INSERT INTO prefs (k, u, data) VALUES ('prefs', ?, ?) "
                "ON CONFLICT(k) DO UPDATE SET u=excluded.u, data=excluded.data WHERE excluded.u > prefs.u",
                (int(prefs.get("u") or 0), json.dumps(prefs, ensure_ascii=False)),
            )
        db.commit()
        logs = [json.loads(r[0]) for r in db.execute("SELECT data FROM logs ORDER BY json_extract(data, '$.ts')")]
        row = db.execute("SELECT data FROM prefs WHERE k='prefs'").fetchone()
    return {"logs": logs, "prefs": json.loads(row[0]) if row else None}


class Handler(BaseHTTPRequestHandler):
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def reply(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/sync":
            return self.reply(404, {"error": "not found"})
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), f"Bearer {TOKEN}".encode()):
            return self.reply(401, {"error": "密碼錯誤"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.reply(413, {"error": "資料太大"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.reply(400, {"error": "格式錯誤"})
        self.reply(200, merge(payload))

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    if len(TOKEN) < 8:
        raise SystemExit("請設定 GYM_TOKEN 環境變數（至少 8 個字元）")
    print(f"同步伺服器運行中 http://{HOST}:{PORT}  資料庫 {DB_PATH}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
