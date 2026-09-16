# 本機完整 Docker 環境

## 架構

```text
Browser → 127.0.0.1:8100 → web（Gunicorn + Django）
                              ├─ PostgreSQL：postgres:5432
                              ├─ Redis：redis:6379
                              └─ Selenium：selenium:4444（影片預覽）

Redis → worker（Celery solo）
          ├─ Selenium：selenium:4444（留言抓取）
          ├─ PostgreSQL：postgres:5432
          └─ DeepSeek API（AI 報告）
```

Web 與 Worker 使用同一個 Python image；Selenium 使用官方 Standalone Chromium image。Selenium 預設一次只接受一個瀏覽器 session，Celery 也維持目前的 `solo` 模式，避免同一台開發電腦同時開啟過多瀏覽器。

## 第一次啟動

保留現有 `.env.postgres`，並確認啟動 Compose 的 PowerShell 能讀取 `DEEPSEEK_API_KEY`：

```powershell
[bool]$env:DEEPSEEK_API_KEY
```

應顯示 `True`，Compose 會將它傳給 Worker。不要把金鑰寫進 Compose 或 Git。

另外建議複製 `.env.docker.example` 為 `.env.docker`，填入：

```dotenv
DJANGO_SECRET_KEY=一段夠長的隨機內容
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
```

`.env.docker` 已排除 Git。不要將正式 Secret Key 填入 `.env.docker.example`。

啟動並建立 image：

```powershell
docker compose up -d --build
docker compose ps
```

Web 啟動時會執行尚未套用的 Django migrations、收集靜態檔，再由 Gunicorn 監聽容器內的 8000。主機從 `http://127.0.0.1:8100/` 進入。

`redisinsight` 屬於 `local-tools` profile，不會隨一般的 `docker compose up` 啟動。它只是 Redis 的圖形管理工具，正式環境不需要。若本機需要查看 queue 或 key，再另外啟動：

```powershell
docker compose --profile local-tools up -d redisinsight
```

只停止 RedisInsight（保留其 volume 資料）：

```powershell
docker compose stop redisinsight
```

Redis 本身仍是目前 Celery 的 broker，Web 呼叫 `.delay()` 與 Worker 接收任務都需要它，因此不可直接從正式環境移除。若未來改用雲端託管 Redis，只需將 `CELERY_BROKER_URL` 指向託管服務，再另外調整正式環境 Compose。

## 日常操作

```powershell
docker compose up -d
docker compose logs -f web worker selenium
docker compose stop
```

程式碼修改後需重建 Web/Worker image：

```powershell
docker compose up -d --build web worker
```

只重新啟動個別服務：

```powershell
docker compose restart web
docker compose restart worker
```

不要同時啟動 PyCharm 的 Django/Celery 與 Docker 的 Web/Worker，否則可能產生連接埠衝突，或讓兩個 Worker 同時取走 Queue 任務。

## Selenium 模式

容器設定 `SELENIUM_REMOTE_URL=http://selenium:4444/wd/hub`，因此 Provider 會建立遠端瀏覽器 session。本機 PyCharm 沒有設定該變數時，仍由 Selenium Manager 啟動 Windows Chrome，既有偵錯方式不變。

Selenium Grid 狀態頁只綁定本機：`http://127.0.0.1:4444/`。若要看實際瀏覽器畫面，需另行啟用 noVNC 連接埠；目前專案使用 headless 模式，沒有公開該連接埠。

## 停止與資料安全

`docker compose stop` 只停止容器，PostgreSQL、Redis 與 RedisInsight volumes 都會保留。不要執行 `docker compose down -v`，除非確定要刪除資料 volumes。

PostgreSQL volume 不是備份；仍應定期執行：

```powershell
.\.venv\Scripts\python.exe scripts/backup_postgres.py --verify
```

## 目前範圍

這是本機容器化環境，不是可直接公開上線的 production 組態。後續仍需處理 Nginx、HTTPS、正式網域、Secret 管理、備份保存政策、監控，以及將容器 image 發佈到部署環境。
