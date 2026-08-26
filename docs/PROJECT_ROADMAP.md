# TubeSense AI 專案開發路線

這份文件是 TubeSense AI 的共同開發依據，用來記錄與 Codex 協同開發時的目前位置、各階段目標、工作項目及完成條件。

原則是先建立可執行、可測試的 Django 基礎，再完成雙資料來源與可靠背景任務，最後才串接 AI、容器化和部署。每完成一個小階段就測試並 Commit，不一次堆疊大量未驗證功能。

## 目前進度

```text
階段 0：專案與開發環境       已完成
階段 1：Django 基礎          已完成
階段 2：共用 UI 與新增分析    進行中  ← 目前位置
階段 3：資料模型與 Provider   尚未開始
階段 4：YouTube 雙來源        尚未開始
階段 5：背景任務與進度頁      尚未開始
階段 6：AI 分析與報告頁       尚未開始
階段 7：測試、安全與可觀測性  尚未開始
階段 8：Docker 與 AWS 部署    尚未開始
```

## 階段 0：專案與開發環境

目標：建立可重建、可追蹤、可推送的 Python 開發環境。

- [x] 建立 Git Repository 與 `main` 分支。
- [x] 建立遠端 Repository 並完成第一次 Push。
- [x] 建立 Python 3.13 虛擬環境。
- [x] 建立 `requirements.txt` 與 `requirements-dev.txt`。
- [x] 安裝 Django 5.2 LTS。
- [x] 建立 `.gitignore`，排除虛擬環境、IDE 設定、資料庫與敏感檔案。
- [x] 將 Stitch 原始素材保留在本機，不提交 Git。

完成條件：

- 可以由 requirements 檔案重新安裝依賴。
- `python -m django --version` 正常顯示版本。
- 基準 Commit 已推送到遠端。

## 階段 1：Django 基礎

目標：理解並完成可執行的 Django 專案骨架、語言、時區與初始資料庫。

- [x] 使用 `startproject` 建立 `config` 與 `manage.py`。
- [x] 通過 `python manage.py check`。
- [x] 啟動開發伺服器並看到 Django 歡迎頁。
- [x] 正確加入 `LocaleMiddleware`。
- [x] 設定預設繁體中文與英文候選語言。
- [x] 將時區設定為 `Asia/Taipei`。
- [x] 理解 migration 並套用 Django 內建 migration。
- [x] 建立 Django Admin 帳號並登入管理頁。
- [x] 建立專案 README 與 Roadmap。
- [x] 完成 Django 基礎階段 Commit 與 Push。

完成條件：

- `python manage.py check` 無錯誤。
- Django 實際載入 `zh-hant` 與 `Asia/Taipei`。
- 內建 migration 全部套用。
- 可以登入 `/admin/`。
- Git 沒有非預期檔案。

## 階段 2：共用 UI 與新增分析

目標：把 Stitch 的 Desktop／Mobile 設計整理成同一套 Django Template RWD 介面，完成頁面 1、2。

- [x] 建立 `analyses` Django App，作為分析功能的程式邊界。
- [x] 建立共用 `base.html`、側邊導覽、手機頂部列與 Logo。
- [x] 將品牌統一為 TubeSense AI，使用紫色播放圖示。
- [x] 建立靜態檔案與 Tailwind CSS 開發流程。
- [x] 完成頁面 1「分析總覽」極簡版。
- [x] 完成頁面 2「新增分析」單一步驟表單。
- [x] 使用後端驗證支援 watch、youtu.be、shorts、live 等 YouTube 網址。
- [ ] 使用 HTMX 在輸入網址後顯示影片預覽或錯誤。
- [ ] 加入 Selenium／YouTube API 資料來源選擇。
- [x] 驗證 Desktop 與 Mobile 不跑版。
- [x] Template 文字使用可翻譯標記，為中英文切換保留能力。

完成條件：

- 同一份 Template 能正確顯示 Desktop 與 Mobile。
- 有效網址顯示影片縮圖與基本資料，無效網址顯示明確原因。
- 表單能保存使用者選擇的資料來源。

## 階段 3：資料模型與 Provider 介面

目標：先定義資料和邊界，再實作 Selenium／API，避免抓取邏輯和網站流程綁死。

- [ ] 設計 `Video`、`Comment`、`AnalysisJob`、`FetchRun` 模型。
- [ ] 設計 `CommentObservation`，記錄每次抓取看到的留言。
- [ ] 設計 `JobLog` 與 `AnalysisResult`。
- [ ] 建立並審查 migration。
- [ ] 定義 `VideoData`、`CommentData`、`FetchOptions` DTO。
- [ ] 定義 `YouTubeProvider` 共用介面。
- [ ] 建立 Fake Provider，先測試 Service，不連接外部網站。
- [ ] 建立 `YouTubeFetchService`，Provider 不直接寫入資料庫。
- [ ] 為網址解析、資料正規化與去重建立測試。

完成條件：

- Service 可以替換 Provider，不需要修改 View 或 Model。
- 同一支影片重複執行不會重複建立相同留言。
- 每次執行都能追蹤來源、時間、數量與錯誤。

## 階段 4：YouTube 雙資料來源

目標：YouTube Data API 與 Selenium 都能輸出相同資料格式，並可逐次選擇和比較。

### YouTube Data API

- [ ] 建立 Google Cloud 專案、API Key 與安全環境變數。
- [ ] 實作影片資訊查詢。
- [ ] 實作留言分頁與回覆留言查詢。
- [ ] 處理 quota、留言關閉、私人影片與不存在影片。
- [ ] 記錄 API 頁數、quota 相關資訊與執行時間。

### Selenium

- [ ] 將現有單機 Selenium 程式重構為 Provider。
- [ ] 移除寫死的影片網址、ChromeDriver 路徑、`input()` 與終端機專用輸出。
- [ ] 支援 `managed`、`remote_debug`、`remote` 三種 Driver 模式。
- [ ] 取得穩定留言 ID，保存父留言與回覆關係。
- [ ] 將留言分批輸出，不等全部抓完才回傳。
- [ ] 處理排序、懶載入、逾時、瀏覽器崩潰與 YouTube 版面變動。
- [ ] 建立可重現的 Selenium 測試影片清單。

### 來源比較

- [ ] 同一影片分別建立 API 與 Selenium `FetchRun`。
- [ ] 比較留言總數、共同留言、單邊缺少留言、回覆完整度和時間。
- [ ] 不在任務執行途中自動切換來源。

完成條件：

- 新任務可以明確選擇任一來源。
- 兩個 Provider 都回傳相同 DTO。
- 來源失敗時保留可理解的錯誤碼與 Log。

## 階段 5：背景任務與分析進度頁

目標：耗時抓取不阻塞 Web Request，使用者能看到任務在哪個階段及為何失敗。

- [ ] 加入 Redis 與 Celery。
- [ ] 分離 `youtube_api`、`youtube_selenium`、`analysis` Queue。
- [ ] Selenium Worker 初期 concurrency 設為 1。
- [ ] 建立任務狀態、階段、百分比與結構化 Log 更新方式。
- [ ] 實作重試、逾時、取消與錯誤分類。
- [ ] 完成頁面 3「分析進度」。
- [ ] 使用 HTMX polling 更新進度和 Log。
- [ ] 任務完成後導向報告頁。
- [ ] 評估實際需求後再決定是否改用 WebSocket。

規劃狀態：

```text
pending → running → awaiting_analysis → completed
              ├── retry
              ├── cancelled
              └── failed
```

完成條件：

- 關閉瀏覽器不會中止背景任務。
- Web Worker 不直接執行 Selenium。
- 使用者重新整理頁面後仍能看到真實進度與 Log。
- 錯誤不只出現在 Worker 終端機，也會保存到資料庫。

## 階段 6：AI 分析與報告頁

目標：選定 AI 方案後，以可替換介面完成留言分析和頁面 4。

- [ ] 確認 AI 模型、費用、資料限制與批次策略。
- [ ] 定義 AI Provider 介面與結構化輸出 Schema。
- [ ] 實作留言清理、分批、Token 預估與摘要合併。
- [ ] 產生留言摘要、情緒、主題、常見問題、建議與負面回饋。
- [ ] 驗證比例、分類數量與原始留言數一致。
- [ ] 將模型名稱、Prompt 版本和分析時間寫入結果。
- [ ] 完成頁面 4「影片分析報告」。
- [ ] Desktop 與 Mobile 都移除 Top Comments。
- [ ] 加入重新分析與匯出功能的基礎流程。

完成條件：

- 相同輸入與 Prompt 版本可以追蹤結果來源。
- AI 回傳格式錯誤時不會寫入不完整報告。
- 頁面 4 可顯示真實資料，不使用假 AI 結果冒充完成。

## 階段 7：測試、安全與可觀測性

目標：讓專案不只在開發者電腦上偶爾成功，而是能驗證、診斷與安全運作。

- [ ] Model、Service、Provider 和 View 單元測試。
- [ ] HTMX 端點與完整主要流程整合測試。
- [ ] Selenium 失敗情境和版面變動偵測測試。
- [ ] 環境變數管理 Secret Key、API Key 與資料庫密碼。
- [ ] 設定 production 的 `DEBUG`、`ALLOWED_HOSTS`、CSRF、HTTPS 與安全 Header。
- [ ] 加入結構化 Log、健康檢查與錯誤追蹤。
- [ ] 定義資料保留、任務清理與備份方式。
- [ ] 執行 Django deployment check。

完成條件：

- 主要流程有自動化測試。
- Repository 不包含密鑰或正式環境資料。
- 能從 Log 回答任務在哪裡、使用哪個來源及為何失敗。

## 階段 8：Docker 與 AWS 部署

目標：使用可重建的容器部署到 AWS EC2，並保留後續擴充空間。

- [ ] 建立 Django Dockerfile 與 production 啟動方式。
- [ ] 建立 Docker Compose：Nginx、Web、Worker、Redis、PostgreSQL。
- [ ] 使用官方 Selenium Standalone Chrome 容器並固定版本。
- [ ] Selenium 容器設定足夠 shared memory，連接埠不公開到網際網路。
- [ ] 分離 development 與 production 設定。
- [ ] 在本機完成完整容器整合測試。
- [ ] 規劃 ECR Image 推送流程。
- [ ] 部署到 EC2，設定 Domain、HTTPS、Security Group 與 SSM。
- [ ] 決定 PostgreSQL 使用 RDS 或 EC2 容器。
- [ ] 規劃 CloudWatch、S3、備份與 Secret 管理。
- [ ] 完成正式環境 smoke test 與復原流程。

完成條件：

- 新 EC2 可以依文件重建服務。
- Web、API Worker、Selenium Worker 與 AI Worker 彼此隔離。
- Redis、PostgreSQL 和 Selenium 不直接暴露到公開網路。
- 更新失敗時有可操作的回復方式。

## 頁面 5～8：核心流程完成後再安排

- [ ] 頁面 5：分析紀錄。
- [ ] 頁面 6：留言探索器。
- [ ] 頁面 7：系統狀態。
- [ ] 頁面 8：AI 洞察中心。

這些頁面不阻擋 MVP。開始前會重新確認功能價值、資料來源與 UI，而不是只因為已有 Stitch 畫面就直接實作。

## Git 工作流程

每個階段採用小步提交：

```powershell
git status
git diff
git add <本次相關檔案>
git diff --staged
git commit -m "type: 簡短描述"
git push
```

建議 Commit 類型：

- `docs:` 文件與說明。
- `feat:` 新功能。
- `fix:` 錯誤修正。
- `refactor:` 不改變行為的結構調整。
- `test:` 測試與驗證工具。
- `chore:` 環境、建置及維護工作。

不要把多個階段塞在同一個 Commit。每次提交前至少執行一次測試，並檢查 `git diff --staged`。

## Roadmap 更新規則

- 開始一個工作項目時，不先勾選完成。
- 實作、測試都通過後才將 `[ ]` 改成 `[x]`。
- 每次重要 Commit 後更新「目前進度」。
- 發現新需求時先放入對應階段，避免中途擴大目前範圍。
- 技術選型改變時，同步更新 README 與本文件。
