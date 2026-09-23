# TubeSense AI：EC2 Docker 部署

GitHub Actions 自動部署的 IAM、OIDC 和 SSM 設定見 [GITHUB_ACTIONS_DEPLOYMENT.md](GITHUB_ACTIONS_DEPLOYMENT.md)。

第一版以單台 `t3.micro`、單一 Gunicorn Worker 與單一 Celery Worker 運行。Selenium 備援來源限制為 200 則留言；正式環境使用 YouTube Data API 完整分頁抓取，並保留 2 GiB Swap、不啟動 RedisInsight。

## 1. 準備環境檔

從範例建立兩個不提交 Git 的檔案：

```bash
cp .env.postgres.example .env.postgres
cp .env.production.example .env.production
chmod 600 .env.postgres .env.production
```

請設定強密碼、隨機 `DJANGO_SECRET_KEY`、EC2 公開 IP 或 Domain、DeepSeek API Key，以及已啟用 YouTube Data API v3 的 `YOUTUBE_API_KEY`。`DJANGO_ALLOWED_HOSTS` 使用逗號分隔且不包含 `http://`。

`TUBESENSE_HTTP_PORT` 是 TubeSense Nginx 對主機公開的 HTTP Port。獨立部署可使用 `80`；若主機的 TCP 80 已被其他 Gateway 使用，則設為未占用的 Port，例如 `8090`。正式部署命令必須保留 `--env-file .env.production`，Compose 才能在解析 `ports` 時讀到此值。

正式環境應保持 `YOUTUBE_DATA_SOURCE=youtube_api`；本機開發未設定時則預設使用 Selenium。API Key 只放在 `.env.production`，不可提交 Git。

可用下列命令產生足夠長的 Django Secret Key：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 2. 啟動正式服務

```bash
docker compose --env-file .env.production -f compose.production.yaml config
docker compose --env-file .env.production -f compose.production.yaml up -d --build --remove-orphans
docker compose --env-file .env.production -f compose.production.yaml ps
```

正式 Compose 只公開 Nginx 的 `TUBESENSE_HTTP_PORT`（預設 TCP 80）。Django、PostgreSQL 與 Redis 都只存在於 Docker 內部網路；正式環境使用 YouTube Data API，不啟動 Selenium 容器。

AWS Security Group 第一版只需開放：

- TCP 80：網站 HTTP。
- TCP 22：若確實使用 SSH，來源限制為自己的 IP；使用 SSM 時可不公開 SSH。

不要公開 5432、6379 或 8000。

## 3. 驗證

```bash
curl -I http://127.0.0.1/
docker compose --env-file .env.production -f compose.production.yaml logs --tail 100 web
docker compose --env-file .env.production -f compose.production.yaml logs --tail 100 worker
docker stats --no-stream
free -h
```

再從瀏覽器建立一筆分析，確認留言抓取、AI 分析與報告頁完整成功。

正式環境已移除 Selenium 容器的常駐記憶體成本。`t3.micro` 仍保留 2 GiB Swap 並維持一次一項任務；YouTube Data API 不限制留言數，Selenium 備援來源則維持 200 則上限。

## 4. 日常操作

```bash
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs -f --tail 100
docker compose --env-file .env.production -f compose.production.yaml restart worker
docker compose --env-file .env.production -f compose.production.yaml down
```

`down` 不會刪除 PostgreSQL 與 Redis named volume。除非確定要刪除正式資料，否則不要使用 `down -v`。

## 5. 容量監控

```bash
watch -n 2 free -h
vmstat 2
docker stats
sudo dmesg -T | grep -i -E "oom|killed process"
df -h
docker system df
```

若 Selenium 模式經常用滿 2 GiB Swap 或出現 OOM，應先將 `ANALYSIS_MAX_COMMENT_COUNT` 降低，再評估升級主機規格。YouTube API 模式會完整抓取可用留言；若大型影片造成資料庫、AI 輸入或記憶體壓力，應另外設計 API 模式的取樣策略。若 API 回覆 `quotaExceeded`，請到 Google Cloud Console 檢查 YouTube Data API 配額。

HTTPS、Domain、憑證自動續期與正式安全 Header 會在下一階段加入。
