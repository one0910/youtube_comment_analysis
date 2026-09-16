# TubeSense AI：EC2 Docker 部署

第一版以單台 `t3.micro`、單一 Gunicorn Worker、單一 Celery Worker 與 200 則留言上限運行。主機需要保留 2 GiB Swap；正式環境不啟動 RedisInsight。

## 1. 準備環境檔

從範例建立兩個不提交 Git 的檔案：

```bash
cp .env.postgres.example .env.postgres
cp .env.production.example .env.production
chmod 600 .env.postgres .env.production
```

請設定強密碼、隨機 `DJANGO_SECRET_KEY`、EC2 公開 IP 或 Domain，以及 DeepSeek API Key。`DJANGO_ALLOWED_HOSTS` 使用逗號分隔且不包含 `http://`。

可用下列命令產生足夠長的 Django Secret Key：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 2. 啟動正式服務

```bash
docker compose -f compose.production.yaml config
docker compose -f compose.production.yaml up -d --build
docker compose -f compose.production.yaml ps
```

正式 Compose 只公開 Nginx 的 TCP 80。Django、PostgreSQL、Redis 與 Selenium 都只存在於 Docker 內部網路。

AWS Security Group 第一版只需開放：

- TCP 80：網站 HTTP。
- TCP 22：若確實使用 SSH，來源限制為自己的 IP；使用 SSM 時可不公開 SSH。

不要公開 5432、6379、4444 或 8000。

## 3. 驗證

```bash
curl -I http://127.0.0.1/
docker compose -f compose.production.yaml logs --tail 100 web
docker compose -f compose.production.yaml logs --tail 100 worker
docker compose -f compose.production.yaml logs --tail 100 selenium
docker stats --no-stream
free -h
```

再從瀏覽器建立一筆分析，確認留言抓取、AI 分析與報告頁完整成功。

本機完整啟動驗證的閒置基線約為 454 MiB；Selenium 載入 YouTube 後才是記憶體高峰。`t3.micro` 必須保留 2 GiB Swap，且第一版維持 200 則留言上限與一次一項任務。

## 4. 日常操作

```bash
docker compose -f compose.production.yaml ps
docker compose -f compose.production.yaml logs -f --tail 100
docker compose -f compose.production.yaml restart worker
docker compose -f compose.production.yaml down
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

若經常用滿 2 GiB Swap、出現 OOM，或 Selenium 頻繁逾時，應先將 `ANALYSIS_MAX_COMMENT_COUNT` 降低，再評估升級主機規格。

HTTPS、Domain、憑證自動續期與正式安全 Header 會在下一階段加入。
