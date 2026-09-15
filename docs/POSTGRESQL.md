# 本機 PostgreSQL

PostgreSQL 由 `compose.yaml` 的 `postgres` 服務提供。Django 與 Celery 預設共用 PostgreSQL；`config/settings.py` 自動讀取專案根目錄的 `.env.postgres`，已設定的環境變數優先。

2026-09-15 已將本機 SQLite 資料搬入 PostgreSQL，並核對所有模型資料及關聯一致。原始 `db.sqlite3` 保留但不再更新。搬遷備份與匯出位於 `local_debug/postgres_migration_20260915_181314/`（包含帳號與留言資料，不要提交或公開）。

## 初次啟動

從 `.env.postgres.example` 建立 `.env.postgres`，將密碼換成安全的隨機值，再執行：

```powershell
docker compose up -d postgres
docker compose ps postgres
```

安裝 Python 相依套件並建立資料表（全新安裝不會自動匯入舊 SQLite）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
```

本機日常啟動：

```powershell
docker compose up -d postgres redis redisinsight
.\.venv\Scripts\python.exe manage.py runserver 8100
```

另一個終端機啟動 Worker，或使用原本 PyCharm 的 Celery 設定：

```powershell
.\.venv\Scripts\python.exe -m celery -A config worker -l info -P solo -Q youtube_selenium,ai_analysis
```

在 Docker 裡執行 Web/Worker 時需另外設定 `POSTGRES_HOST=postgres`。目前 Web/Worker 仍在 Windows 本機執行，預設 `127.0.0.1:5432`。

## 測試與退回 SQLite

`manage.py test` 預設建立獨立的 `test_tubesense` PostgreSQL 測試庫，結束後由 Django 清理，不是清空 `tubesense`。

只有明確指定 `DATABASE_ENGINE=sqlite` 才會使用 SQLite，PostgreSQL 無法連線不會自動退回：

```powershell
$env:DATABASE_ENGINE = "sqlite"
.\.venv\Scripts\python.exe manage.py test
Remove-Item Env:DATABASE_ENGINE
```

若要退回舊資料庫執行，先停止 Web/Worker，並讓兩者都設定 `DATABASE_ENGINE=sqlite` 再重啟。切換後新增的 PostgreSQL 資料不會自動回寫到 SQLite；退回前必須另外備份並規劃資料同步，不能直接把舊 SQLite 當作最新資料。

`.env.postgres` 已排除 Git。切勿提交或公開密碼。

## 連線

- 主機：`127.0.0.1`
- 連接埠：`5432`
- 資料庫：`tubesense`
- 初始化管理帳號：`admin`
- 密碼：本機 `.env.postgres` 的 `POSTGRES_PASSWORD`

此帳號為官方映像初始化的管理帳號，正式部署前應另建低權限應用程式帳號。
同一 Compose 網路內使用 `postgres:5432`，不是 `127.0.0.1`。

```powershell
docker compose exec postgres psql -U admin -d tubesense
```

進入 psql 後可使用 `\l` 查看資料庫、`\dt` 查看資料表、`\q` 離開。

## 資料保存與停止

資料位於 Docker volume `tubesense-postgres-data`。停止容器不會刪除資料：

```powershell
docker compose stop postgres
docker compose start postgres
```

不要執行 `docker compose down -v`：它可能刪除本專案 PostgreSQL 與 Redis 的資料 volumes。
Volume 不是備份，正式使用前仍需規劃備份與還原。

初始化環境變數只在空資料目錄第一次啟動時建立帳號與資料庫；之後改 `.env.postgres` 不會自動修改既有密碼。
此設定僅綁定本機介面，不公開資料庫至區域網路或網際網路。

官方映像說明：https://hub.docker.com/_/postgres
