# 新版影片分析報告資料契約

狀態：資料契約、Python 事實整理、新版 DeepSeek Provider／解析、模擬預覽均已完成測試。
已在使用者授權下完成一次真實 API Smoke Test，並加入固定成品的唯讀預覽；尚未接入正式資料庫流程。

定案：情緒採整批 AI 估計百分比，不做逐則分類、不換算成留言筆數。少於 30 則只呈現摘要與氛圍。

## 1. 版本與資料流

最終報告 `schema_version = comment-analysis-result-v2`，由 `AIReportV2` 定義。
這是程式組裝後提供儲存／前端的格式，**不是要求 DeepSeek 原樣回傳整份報告**。

留言快照及 Preview → Python 統計／選出 Top 5／建立短引用 → AI 解讀 →
解析與來源驗證 → Python 回填事實 → v2 報告 → Django 模板。

目前 v1 的 Provider、DTO、執行 Service 與預覽頁維持原樣。v2 不繼承 v1，
不把舊資料直接改標為 v2，也不自動升級舊報告。提示詞版本與資料格式版本分開管理。

## 2. 最終報告欄位與 UI 對照

| 欄位 | 型別 | 產生者／用途 |
| --- | --- | --- |
| schema_version | 固定字串 | Python；辨識格式 |
| video | ReportVideoV2 | Selenium Preview 快照；影片資訊卡 |
| sample | ReportSampleV2 | Python；有效去重且實際送入 AI 的筆數、模式、抓取設定 |
| overall_summary | 文字 | AI；整體摘要 |
| atmosphere | 文字 | AI；整體氛圍，小樣本也保留 |
| sentiment | SentimentEstimateV2 或 null | AI 提供百分比與各類說明；程式加入估計標記 |
| topics | ReportTopicV2 清單 | AI；議題名稱、摘要、論述邏輯、引用 |
| top_liked_comments | TopLikedCommentV2 清單 | Python 選最高讚至多 5 則並回填事實，AI 解讀 |
| repeated_text_groups | RepeatedTextGroupV2 清單 | Python；跨顯示名稱的相同文字群組 |
| display_name_activity | DisplayNameActivityV2 清單 | Python；同顯示名稱在同討論串的多則發言 |
| behavior_insights | ReportInsightV2 清單 | AI；對已計算現象的保守解讀 |
| conclusions | ReportInsightV2 清單 | AI；分項總結 |
| risks | 空清單 | 僅供舊 v2 測試成品相容；comment-analysis-v5 之後不再要求 AI 輸出 |
| recommendations | 空清單 | 僅供舊 v2 測試成品相容；comment-analysis-v5 之後不再要求 AI 輸出 |
| limitations | 非空文字清單 | 由 Python 產生的內部限制記錄，不要求 AI 輸出、不在報告頁顯示 |
| identity_notice | 固定字串 | Python；顯示名稱非唯一身分，不以重複發言證明操作 |
| provenance | ReportProvenanceV2 | 程式記錄供應商、模型、提示詞版本、時間、Token |

所有文字都是資料，不是 HTML；前端維持跳脫，不以 `safe` 顯示 AI 原文。
空清單代表本次未列出項目，不代表已證明不存在特定現象或操作。

### 影片與樣本

- `video` 必填 `youtube_video_id`、`title`。其餘為 `channel_name`、`thumbnail_url`、
  `view_count`、`like_count`、`displayed_comment_count`、`published_at`、`duration_seconds`、`captured_at`。
- 未取得的資料用 `null`，不能補設計稿的範例日期、片長或使用 `0` 代替未知。
- 時間若已知，使用含時區的 ISO 8601。缺少精確發布時間不由「幾天前」杜撰。
- `sample`：`analyzed_comment_count`、`top_level_comment_count`、`reply_comment_count`、
  `sort_order`（newest/top）、`include_replies`；`analysis_mode` 由 Python 決定。
- 1–29 則 small；30–200 則 medium；201 則以上 large。0 則不呼叫 AI、不建立報告。
- small 的主要議題與總結各最多 2 項，不傳送重複／活躍群組給 AI，且不產生或顯示行為觀察區塊。
- 主留言＋回覆＝分析數。這是本次送入的樣本，不是宣稱取得全部公開留言。
- 顯示數差異由資料整理層算 `video.displayed_comment_count - sample.analyzed_comment_count`；
  顯示數未知時差異也未知；負差異不可硬改成零，也不可一律解釋成漏抓。

### 情緒（已確認）

```json
{
  "positive": {"percentage": 35, "description": "部分留言肯定影片的說明。"},
  "neutral": {"percentage": 45, "description": "部分留言討論內容或提出問題。"},
  "negative": {"percentage": 20, "description": "部分留言表達不滿。"},
  "method": "ai_batch_estimate",
  "notice": "AI 估計，非逐則分類統計；不代表整體民意。"
}
```

以上為格式示意，非真實分析。比例使用 0–100 的整數，總和 100；拒絕字串、浮點數與布林值。
沒有 `positive_count` 等欄位，也不可自行從比例換算筆數。
固定正面／中立／負面分類，說明需交代情緒指向誰或哪件事；情緒不等同支持率。
small 時整個 `sentiment` 必須是 `null`，改顯示 `atmosphere`。

### 議題、引用與高讚留言

- topic：`name`、`summary`、`reasoning`、`evidence_comment_ids`（至少一則，不能重複）。
  UI 左側顯示論述，右側從來源快照取出引用原文與讚數。
- insight：`title`、`description`、`evidence_comment_ids`。
  新版 AI 回傳的總結與行為解讀必須有來源依據。
- Top 5：`youtube_comment_id`、`author_display_name`、`comment_text`、`like_count`、`interpretation`。
  全部主留言及回覆共同排序，先排除未知讚數，再按讚數遞減；同讚數以輸入 sequence 遞增、
  最後以 ID 字典序作穩定排序。已知 0 讚可排名，少於 5 則就顯示實際數量。
- 最高讚不等於所有觀眾的主流意見，標題應使用「本次樣本高讚留言」。
- API 使用短引用 `c1`、`c2`；最終報告必須轉回原始 ID。未知引用拒絕，不模糊比對或修猜。
- AI 不填作者、讚數及原文；程式從快照回填。敘述文字不要裸露短引用，引用放專用清單。

### 重複與活躍發言

- 重複文字規則：`" ".join(comment_text.split())`，只合併空白；不去除標點、不改大小寫、
  不使用語意相似度。相同文字至少 2 個唯一留言 ID 才成組，可以跨顯示名稱。
- group：`normalized_text`、`author_display_names`、`comment_ids`；`occurrence_count` 由 ID 數計算。
- activity：`author_display_name`、`thread_youtube_comment_id`、`comment_ids`；`comment_count` 由 ID 數計算。
  同顯示名稱、同一根討論串至少 2 則為候選紀錄，不代表異常。根討論串無法可靠解析時不硬歸組。
- 名稱不是帳號 ID；不得宣稱「相同真人」「一定網軍」或「確定非網軍」。
- 只有相對發布時間，不能證明短時間爆量，也不輸出此類量化結論。

## 3. 新版 API 回應分工

模型只需要回傳 `overall_summary`、`atmosphere`、情緒三類比例／說明、議題、
指定 Top 5 的解讀、行為解讀與核心總結。風險、建議與限制不再要求模型輸出。
API 中議題／洞察以 `evidence_comment_refs` 引用；Top 5 解讀用 `comment_ref`＋`interpretation`。
不要求模型計算樣本數、挑選排名、計算重複次數、產出 Preview 或 HTML。
已實作於 `analyses/providers/deepseek_report_v2_provider.py`：

- `SYSTEM_PROMPT_V2`：新版系統提示；`REPORT_PROMPT_VERSION = comment-analysis-v7`。
  提示詞版本與報告格式 `comment-analysis-result-v2` 是不同的版本軸。
- `build_report_user_message(facts)`：全量留言、Preview、精確統計與額外 Top 5／行為群組，
  全部留言依輸入順序使用 c1、c2 等短引用；排名不影響整體分析範圍。
- `parse_report_response(content, facts, provenance)`：離線解析與組裝 `AIReportV2`。
  每層 object 檢查完整且僅允許指定欄位；拒絕錯誤型別、重複 JSON 鍵、NaN／Infinity、
  未知或重複引用、AI 額外填寫的精確事實，以及漏列／替換 Top 5 等狀況。
  AI 的 Top 5 回應順序可不同，Python 最終依來源排名還原。未知讚數不參與排名。
- 議題、總結及行為解讀至少一個引用。
  行為解讀的引用還必須屬於 Python 重複或活躍群組；這不能保證文字解讀的語意正確性。
- `DeepSeekReportV2Provider(...).analyze_report(request, video, sort_order=..., include_replies=...)`
  才會發出真實 API 請求；可選 `source_label` 僅記錄來源標籤，不傳入 AI。
  使用環境變數 `DEEPSEEK_API_KEY`，可注入模擬 client。沿用既有模型／端點設定，
  JSON mode、非串流、max_tokens=12000；SDK timeout=120 秒、max_retries=0。
  不自動重試產生報告，避免解析失敗後悄悄重複付費。網路錯誤向上拋出。
- 回應 finish_reason 必須是 stop；截斷、拒絕或空回應不建立報告。
  未取得 Token 數使用 null，不偽裝成 0。版本、時間與影片統計由 Python 記錄。
- 回傳 `AIReportV2`，由 `report_v2_execution_service.py` 驗證後寫入 `AnalysisResult`；
  舊版 `execute_ai_analysis()` 保留供舊契約測試，不再負責正式 V2 報告。

JSON mode 本身不足以驗證本專案的欄位、引用與來源事實，因此保留嚴格的 Python 驗證。
參考 [DeepSeek 官方 JSON Output 說明](https://api-docs.deepseek.com/guides/json_mode/)。

## 4. 驗證邊界與正式執行流程

本階段類別驗證：型別、非空文字、數量一致性、模式邊界、情緒百分比、
清單格式、重複 ID、Top 5 排序／上限、時間格式。`asdict()` 可序列化成 JSON。
這不是完整 JSON parser；不能直接以巢狀 dict 呼叫 `AIReportV2(**payload)`。

已實作：`analyses/services/ai_report_preparation_service.py`。

- `prepare_report_facts(request, video, sort_order=..., include_replies=...)` 接受已驗證去重的
  `AIAnalysisRequest` 及 `ReportVideoV2`，不讀寫 DB、不呼叫 API、不裁切或修改來源留言。
  回傳 `PreparedReportFacts.request` 保留全部留言；`top_liked_comments` 是額外的排名清單。
- 樣本統計、Top 5、跨名稱重複群組與討論串活躍紀錄皆由 Python 計算。
  群組及群組內留言維持首次輸入順序；只有 Top 5 使用指定排序規則。
- 父留言可沿來源中的連結找到根討論串；缺父留言、自我引用或循環引用不硬歸組。
  `unresolved_thread_comment_ids` 記錄這些 ID，但留言仍保留供 AI 分析。
- 無效讚數、空白名稱等會拒絕，不默默刪除資料或杜撰作者。重複 ID 在 Request 層拒絕；
  輸入必須是同一次抓取的去重快照，不在此層猜哪個衝突版本正確。
- `validate_report_source_facts(report, facts)` 比對影片、樣本、Top 5 名單及原文／作者／讚數、
  重複與活躍群組，以及各區塊引用 ID 是否屬於來源。AI 解讀文字的語意正確性仍非程式可保證。

正式流程已接入：

1. `FetchRun` 永久保存排序方式、是否包含回覆與留言數量上限。
2. Selenium Task 成功後排入 `ai_analysis` Queue，由 `DeepSeekReportV2Provider` 產生報告。
3. `report_v2_execution_service.py` 重算來源事實、驗證報告並以
   `comment-analysis-result-v2` 寫入 `AnalysisResult`；未知 Token 保存為 null。
4. 進度頁每兩秒以 HTMX 更新；任務完成後導向
   `/analyses/jobs/<analysis-job-id>/report/`，由資料庫還原並再次驗證報告。
5. 失敗時停止輪詢並保存失敗階段；Celery 起始或後續 Queue 無法排入時也不會永久停在等待狀態。

## 5. 驗證指令

```powershell
python manage.py test analyses.test_report_v2 -v 2
python manage.py test analyses.test_report_preparation -v 2
python manage.py test analyses.test_deepseek_report_v2 -v 2
python manage.py test analyses.test_report_v2_presentation -v 2
python manage.py test analyses.test_report_v2_artifact -v 2
python manage.py test analyses.test_report_v2_execution -v 2
python manage.py test analyses -v 1
```

以上皆為離線測試，不呼叫 DeepSeek、不產生 API 費用。

## 6. 正式報告呈現

- 正式流程只透過 `/analyses/jobs/<analysis-job-id>/report/` 顯示已完成並經來源驗證的報告。
- 開發階段使用的模擬與真實成品預覽 URL 已移除，不再暴露額外報告入口。
- `report_v2_presentation_service.py` 只負責將已驗證的報告轉成畫面所需的 context。
- 模擬資料已移至 `analyses/testing/report_v2_factory.py`，僅供離線測試使用，不對外提供路由。
- `report_v2.html` 使用專案既有的 Tailwind v4 bundle 與現有 base/sidebar；已移除獨立的
  `report-v2.css`，避免維護兩套設計系統。沒有引入 Stitch 的 CDN Tailwind、固定頁面高度、
  隱藏 scrollbar 或未實作的操作。
- 字級依 Stitch 規範調整：一般報告文字以 16px 為主、整體摘要 18px、區塊標題 20–24px，
  同時保留專案的繁體中文字型 fallback。圓環的動態比例仍由 SVG attribute 呈現。
- 圓環與圖例顯示估計比例，不顯示分類筆數；議題、行為與總結可查看引用原文，
  高讚表格採緊湊單行並移除解讀展開，過長原文保留於可獨立橫向捲動的表格中。
  只調整顯示，資料格式中的 interpretation 仍保留，其他區塊待真實資料接入後再調整。
- 缺少的影片縮圖、發布時間及片長以未知狀態呈現，不自行補值。
- `report_v2_artifact_service.py` 僅負責將資料庫內的 JSON 還原為嚴格 DTO，並拒絕未知或遭竄改的衍生欄位。
