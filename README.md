# TubeSense AI

TubeSense AI 是一個 YouTube 留言 AI 分析平台，也是用來練習 Django、Selenium、非同步任務與雲端部署的 Side Project。

使用者輸入 YouTube 影片網址後，可以選擇透過 YouTube Data API 或 Selenium 取得影片與留言資料。系統會在背景處理資料、顯示即時進度與執行 Log，最後產生情緒、主題、常見問題、觀眾建議及負面回饋等分析報告。

本專案目前採取小步開發：先完成頁面 1～4 和主要分析流程，頁面 5～8 留待核心功能穩定後再實作。詳細進度請見 [PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)。

## 核心需求

- 介面預設使用繁體中文，架構保留中英文切換能力。
- 同一套 Django Template 支援 Desktop 與 Mobile，不維護兩份頁面。
- 輸入網址後先驗證格式，並顯示影片縮圖、標題、作者、觀看數與留言數。
- 每次任務可以明確選擇 Selenium 或 YouTube Data API。
- Selenium 是正式資料來源之一，也是本專案的重點練習項目。
- 背景任務顯示處理階段、百分比與執行 Log。
- 同一支影片可以分別執行兩種來源，保留紀錄供日後比較。

## MVP 頁面

1. 分析總覽：採用簡潔版首頁，Desktop 與 Mobile 不跑版。
2. 新增分析：單一步驟輸入網址、驗證影片並選擇資料來源。
3. 分析進度：顯示背景任務進度、分析階段及系統 Log。
4. 影片分析報告：顯示 AI 摘要、情緒分布、正負面重點；不顯示 Top Comments。

原始 Stitch 設計保存在本機的 `stich素材+html+png`，不提交到 Git。實作時會整理成共用 Layout 與 RWD 元件，不直接複製 16 份獨立 HTML。

## 技術選型

### 已確定

| 分層 | 技術 | 用途 |
| --- | --- | --- |
| 語言 | Python 3.13 | 後端、資料擷取與背景任務 |
| Web Framework | Django 5.2 LTS | Model、View、Template、Admin 與資料庫操作 |
| 前端互動 | Django Template + HTMX | 表單驗證、局部更新、進度輪詢 |
| 樣式 | Tailwind CSS（規劃） | 依 Stitch 視覺稿建立 RWD 介面 |
| 主要資料庫 | PostgreSQL | 影片、留言、任務、Log 與分析結果 |
| 開發初期資料庫 | SQLite | 學習 Django 與建立初始資料表，之後切換 PostgreSQL |
| 暫存與 Broker | Redis | Celery Broker、快取與短期狀態 |
| 背景任務 | Celery | 執行 API／Selenium 抓取和 AI 分析 |
| 資料來源 | Selenium | 瀏覽器自動化取得影片與留言，保留練習價值 |
| 資料來源 | YouTube Data API | 使用官方 API 取得影片與留言 |
| 容器 | Docker + Docker Compose | 統一本機、測試與 EC2 執行環境 |
| 部署 | AWS EC2 + Nginx + Gunicorn | 正式環境 Web 服務與反向代理 |

### 待後續評估

- AI 模型與供應商。
- 圖表函式庫。
- PostgreSQL 使用 EC2 容器或 Amazon RDS。
- S3、CloudWatch、ECR 與 Secrets Manager 的導入時機。
- WebSocket；MVP 的進度頁先使用 HTMX polling。

## 系統架構

```text
Browser
   │
   ▼
Nginx → Django View → Django Template + HTMX
              │
              ├── PostgreSQL（持久資料）
              │
              └── Redis → Celery Worker
                            │
                            ├── YouTubeApiProvider
                            ├── YouTubeSeleniumProvider → Selenium Chrome
                            └── AI Analysis Provider（待選型）
```

兩種 YouTube 資料來源會遵守相同的 Provider 介面：

```text
YouTubeFetchService
        │
        ├── YouTubeApiProvider
        └── YouTubeSeleniumProvider
                 │
                 ▼
        統一 VideoData／CommentData
                 │
                 ▼
             PostgreSQL
```

View、Celery Worker 和 AI 分析層只處理統一資料格式，不直接依賴 Selenium 或 API。每個分析任務在開始前選定來源，執行途中不切換，避免重複資料和不可重現的結果。

## 預計資料層級

```text
Model     保存 Video、Comment、AnalysisJob、FetchRun、JobLog、AnalysisResult
Service   負責流程編排、資料正規化與資料庫寫入
View      接收 HTTP 請求並回傳完整或局部 Template
Template  顯示頁面與共用元件
HTMX      局部更新 URL 預覽、進度與 Log
Worker    執行耗時的資料擷取和 AI 分析
Provider  隔離 Selenium、YouTube API 與未來 AI 供應商
```

## 本機開發

### 建立虛擬環境

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements-dev.txt
```

### 啟動目前的 Django 專案

```powershell
python manage.py check
python manage.py runserver
```

瀏覽 `http://127.0.0.1:8000/`。目前仍在 Django 基礎建置階段，尚未建立產品頁面。

## 開發原則

- 先打通一條可驗證的主要流程，再增加進階功能。
- 使用者親自執行主要開發步驟，Codex 負責說明、審查與除錯。
- 程式碼註解使用白話中文，只解釋必要的設計原因。
- 終端機 Python 測試採用條列步驟；需要輸出時使用 Rich 的 `rprint`。
- Django Template 的 HTML `class` 屬性原則上保持單行，方便在 IDE 中搜尋與修改 Tailwind utilities。
- 每個階段採用小步 Commit，提交前檢查 `git diff --staged`。
- 密碼、API Key、Django Secret Key 不提交 Git。

## Git Commit 類型

- `docs:` 文件與說明。
- `feat:` 新功能。
- `fix:` 錯誤修正。
- `refactor:` 不改變行為的結構調整。
- `test:` 測試與驗證。
- `chore:` 環境、建置與維護工作。
