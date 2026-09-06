"""可重現的開發用假資料及前端呈現整理，不呼叫 API、不依賴 temporary 檔案。"""

import json

from analyses.providers.ai_analysis_provider import AIAnalysisRequest, AICommentInput
from analyses.providers.ai_report_v2 import ReportProvenanceV2, ReportVideoV2
from analyses.providers.deepseek_report_v2_provider import parse_report_response
from .ai_report_preparation_service import prepare_report_facts, validate_report_source_facts


def build_report_preview_fixture(*, small: bool = False):
    """所有影片、留言、讚數與解讀皆為虛構，專用於版面驗證。"""
    texts = (
        "自動化很方便，但重要的結果還是要自己確認。",
        "把資料整理交給程式、把解讀交給 AI，這個分工很清楚。",
        "希望下一集示範失敗時怎麼重試，不然新手很容易卡住。",
        "流程圖很清楚，終於知道每一步在做什麼。",
        "能不能分享適合初學者的練習資料？",
        "工具能節省時間，但不能省略資料來源的查證。",
        "請問這套流程一定要有付費帳號嗎？",
        "測試資料和真實資料分開，這個做法值得學。",
        "字幕有幾個地方太快，希望停留久一點。",
        "謝謝整理，期待下一集！",
        "有實際錯誤案例會更好。",
        "我比較想看結果如何存回資料庫。",
        "終於理解為什麼不能只看 AI 的回答。",
        "希望提供章節時間，方便回頭查找。",
        "成本的部分可以再多講一些。",
        "請問資料量增加後要怎麼處理？",
        "謝謝整理，期待下一集！",
        "也想看手機版的報告畫面。",
        "分工的概念很實用。",
        "想了解輸入資料如何清理。",
        "我也覺得重要結果需要人工核對。",
        "例如金額或日期，就不適合直接照抄。",
        "同意，先確認來源再做結論。",
        "流程清楚，但安裝步驟還可以再慢一點。",
        "原來測試也能不用真的呼叫 API。",
        "我也是在重試的地方卡住。",
        "希望能加上錯誤訊息的說明。",
        "小量資料先測試，確認後再放大很重要。",
        "期待看到完整的實作版本。",
        "謝謝，這樣知道該從哪一步開始了。",
    )
    likes = (389, 150, 100, 57, 43, 72)
    comments = tuple(
        AICommentInput(
            sequence=i + 1, youtube_comment_id=f"demo-{i + 1}",
            parent_youtube_comment_id=None if i < 20 else ("demo-1" if i < 25 else "demo-3"),
            author_display_name="@示範觀眾_A" if i in (20, 21, 22) else f"@示範觀眾_{i + 1:02}",
            comment_text=text, like_count=likes[i] if i < 6 else i % 7,
            published_time_text="1 天前（模擬）", is_pinned=False,
        ) for i, text in enumerate(texts)
    )
    if small:
        comments = comments[:3]
    request = AIAnalysisRequest("demo-video", "【示範影片】把工作流程交給 AI 之前：自動化與人工查證的分工", comments)
    video = ReportVideoV2(
        request.youtube_video_id, request.video_title, channel_name="TubeSense 示範頻道",
        view_count=125480, like_count=1309, displayed_comment_count=36,
        captured_at="2026-09-05T10:00:00+08:00",
    )
    facts = prepare_report_facts(request, video, sort_order="newest", include_replies=not small)
    refs = {comment.youtube_comment_id: f"c{i}" for i, comment in enumerate(comments, 1)}
    payload = {
        "overall_summary": "這份示範報告呈現觀眾對自動化教學的回饋：一方面肯定分工清楚，另一方面期待更多錯誤處理與上手案例。所有內容僅供版面測試。",
        "atmosphere": "討論以學習與具體提問為主。肯定多指向清楚的流程說明，保留意見則聚焦於教學節奏及實作細節；不能據此推論所有觀眾的看法。",
        "sentiment": None if small else {
            "positive": {"percentage": 35, "description": "肯定自動化與人工查證的分工，認為流程容易理解。"},
            "neutral": {"percentage": 45, "description": "詢問成本、練習資料及後續實作，以資訊需求為主。"},
            "negative": {"percentage": 20, "description": "對字幕速度及錯誤處理說明不足表達保留意見。"},
        },
        "topics": [
            {"name": "效率提升與人工查證之間的分工", "summary": "觀眾肯定工具協助，但提醒不可省略核對。",
             "reasoning": "留言將『整理資料』與『判斷結果』分開看待。正向回饋並非完全信任 AI，而是認同工具能協助重複工作，同時保留人的核對責任。",
             "evidence_comment_refs": ["c1", "c2"]},
            {"name": "從概念理解到實際操作，仍需要更多案例", "summary": "具體的重試與錯誤說明，是後續內容可以補足的方向。",
             "reasoning": "這類留言提出明確的學習需求，不能直接視為否定影片品質。提供可重現的失敗案例，可能有助於觀眾理解流程的限制。",
             "evidence_comment_refs": ["c3"] if small else ["c3", "c9", "c11"]},
        ],
        "top_liked_comments": [
            {"comment_ref": refs[c.youtube_comment_id], "interpretation": "這則示範留言反映對流程分工或實作細節的關注；高讚數不等於所有觀眾的共同立場。"}
            for c in facts.top_liked_comments
        ],
        "behavior_insights": [] if small else [
            {"title": "相同文字出現在不同顯示名稱下", "description": "兩則留言使用相同的致謝文字。這只證明文字重複，無法判定使用者之間有關聯或操作意圖。", "evidence_comment_refs": ["c10", "c17"]},
            {"title": "同一討論串中的多次發言", "description": "相同顯示名稱在查證相關討論串補充多則意見，屬於可觀察的參與紀錄，不直接判定為洗版。", "evidence_comment_refs": ["c21", "c22", "c23"]},
        ],
        "conclusions": [
            {"title": "分工清楚是內容的主要亮點", "description": "示範留言將工具效率與人工核對並列，適合在後續內容繼續說明兩者如何互補。", "evidence_comment_refs": ["c1", "c2"]},
            {"title": "實作細節是下一步資訊需求", "description": "錯誤處理案例有助於把概念轉成實際操作；這是樣本中的具體建議，而非對整體觀眾需求的量化判斷。", "evidence_comment_refs": ["c3"]},
        ],
    }
    provenance = ReportProvenanceV2("fixture", "未呼叫模型", "ui-fixture-v2", "2026-09-05T10:00:00+08:00", source_label="內建模擬資料")
    report = parse_report_response(json.dumps(payload, ensure_ascii=False), facts, provenance)
    return report, facts


def build_report_preview_context(report, facts, *, is_fixture: bool = True) -> dict:
    validate_report_source_facts(report, facts)
    comments = {c.youtube_comment_id: c for c in facts.request.comments}
    analysis_mode = report.sample.analysis_mode.value
    sample_mode_details = {
        "small": "小型樣本模式（情況 A）",
        "medium": "中型樣本模式（情況 B）",
        "large": "大型樣本模式（情況 C）",
    }

    def panels(items, *, evidence_limit=None):
        return [
            {"item": item, "evidence": [comments[i] for i in item.evidence_comment_ids[:evidence_limit]]}
            for item in items
        ]

    sentiment_rows = []
    offset = 0
    if report.sentiment:
        for key, label, color in (("positive", "正面", "#14805e"), ("neutral", "中立", "#858897"), ("negative", "負面", "#bc0100")):
            category = getattr(report.sentiment, key)
            sentiment_rows.append({"label": label, "category": category, "color": color, "offset": -offset})
            offset += category.percentage
    return {
        "page_title": "新版影片分析報告", "report": report, "facts": facts, "sentiment_rows": sentiment_rows,
        "is_fixture": is_fixture,
        "sample_mode_detail": sample_mode_details[analysis_mode],
        "topic_panels": panels(report.topics, evidence_limit=3), "behavior_panels": panels(report.behavior_insights),
        "conclusion_panels": panels(report.conclusions),
    }
