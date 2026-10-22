# 同步伺服器安裝說明（給 Claude 看）

> 你好，Claude。這份說明是另一個 Claude session 寫的。用戶要把這個同步伺服器裝在這部遠端 Linux 虛擬機上，讓 24 小時運行。請照下面的步驟做，遇到需要用戶決定的地方（例如網域名稱）再問用戶。

## 這是甚麼

- 網頁 app 在 `https://hingaa4.github.io/gym/`（GitHub Pages，repo `hingaa4/gym`），是用戶在 iPhone 上的健身記錄 app。
- `server.py` 是同步伺服器。app 每記錄一組，就會 POST 到 `/api/sync`，伺服器用 SQLite 存起來。
- 只用 Python 3 標準庫，**不需要 pip install**，Python 3.9 或以上就可以。
- 設定全部用環境變數：`GYM_TOKEN`（必填）、`GYM_DB`、`GYM_PORT`（預設 8787）、`GYM_HOST`（預設 127.0.0.1）、`GYM_ORIGIN`（預設 `https://hingaa4.github.io`）。

## 硬性要求：一定要 HTTPS

App 是 https 頁面，Safari 會擋住對 http 伺服器的請求（mixed content），所以伺服器**必須有一個有效證書的 https 網址**。伺服器本身只聽 `127.0.0.1:8787`，HTTPS 由前面的反向代理負責。

## 步驟

### 1. 安裝檔案

```bash
sudo useradd --system --home /opt/gym-sync --shell /usr/sbin/nologin gym || true
sudo mkdir -p /opt/gym-sync
sudo curl -fsSL https://raw.githubusercontent.com/hingaa4/gym/main/server/server.py -o /opt/gym-sync/server.py
sudo curl -fsSL https://raw.githubusercontent.com/hingaa4/gym/main/server/gym-sync.service -o /etc/systemd/system/gym-sync.service
sudo chown -R gym:gym /opt/gym-sync
python3 --version   # 需要 3.9+
```

### 2. 產生同步密碼

```bash
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
printf 'GYM_TOKEN=%s\nGYM_DB=/opt/gym-sync/gym.db\n' "$TOKEN" | sudo tee /etc/gym-sync.env >/dev/null
sudo chmod 600 /etc/gym-sync.env
echo "同步密碼：$TOKEN"   # 最後要告訴用戶
```

### 3. 啟動服務

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gym-sync
curl -s http://127.0.0.1:8787/api/health   # 應該回 {"ok": true}
```

### 4. 設定 HTTPS（三選一，問用戶有沒有網域名稱）

**A. 用戶有自己的網域名稱 → Caddy（推薦）**
1. 叫用戶把一個子網域（例如 `gym.example.com`）的 A 記錄指向這部機的公網 IP。
2. 雲端控制台的防火牆 / security group，以及機上的 ufw/firewalld，都要開放 TCP 80 和 443。
3. 安裝 Caddy（https://caddyserver.com/docs/install ，Debian/Ubuntu 用官方 apt repo），`/etc/caddy/Caddyfile`：
   ```
   gym.example.com {
       reverse_proxy 127.0.0.1:8787
   }
   ```
4. `sudo systemctl reload caddy`，Caddy 會自動申請 Let's Encrypt 證書。

**B. 沒有網域名稱，也不想開端口 → Tailscale Funnel**
1. 安裝 Tailscale 並登入（`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`，用戶要在瀏覽器授權）。
2. `sudo tailscale funnel --bg 8787`
3. 網址會是 `https://<機器名>.<tailnet>.ts.net`，用 `tailscale funnel status` 查看。第一次用 Funnel 可能要用戶在 Tailscale 管理頁面啟用 HTTPS 和 Funnel。

**C. 沒有網域名稱，但可以開 80/443 → DuckDNS 免費子網域 + Caddy**
叫用戶到 https://www.duckdns.org 登入，建立一個子網域指向這部機的 IP，然後照 A 的做法。

> 不要用 `cloudflared tunnel --url`（quick tunnel），它每次重啟網址都會變。

### 5. 驗證

從虛擬機以外的地方測試：

```bash
curl -s https://<網址>/api/health                                 # {"ok": true}
curl -s -X POST https://<網址>/api/sync -H "Authorization: Bearer <密碼>" -d '{}'   # {"logs": [...], "prefs": ...}
curl -s -X POST https://<網址>/api/sync -H "Authorization: Bearer wrong" -d '{}'    # 401 密碼錯誤
```

### 6.（建議）每日備份

```bash
sudo mkdir -p /opt/gym-sync/backup && sudo chown gym:gym /opt/gym-sync/backup
echo '0 4 * * * gym sqlite3 /opt/gym-sync/gym.db ".backup /opt/gym-sync/backup/gym-$(date +\%u).db"' | sudo tee /etc/cron.d/gym-sync-backup
```
（需要 `sqlite3` 指令，沒有的話 `sudo apt install sqlite3`。會保留最近 7 日的備份。）

## 完成後告訴用戶

1. **伺服器網址**，例如 `https://gym.example.com`，不要加 `/api`。
2. **同步密碼**（第 2 步產生的）。
3. 在 iPhone 打開 app → **🗓 歷史** → 最底的 **☁️ 雲端同步**，填網址和密碼，按 **💾 儲存**。看到「☁️ 已同步」就成功了。iPhone 上原有的記錄會自動上傳。

## 排錯

- `journalctl -u gym-sync -f` 查看伺服器記錄。每個請求都會印一行。
- App 顯示「連不上伺服器」：通常是 HTTPS 證書或防火牆有問題，或者 `GYM_ORIGIN` 不是 `https://hingaa4.github.io`（CORS）。
- App 顯示「密碼錯誤」：檢查 `/etc/gym-sync.env` 的 `GYM_TOKEN`。
- 更新伺服器：重新執行第 1 步的 `curl`，然後 `sudo systemctl restart gym-sync`。
