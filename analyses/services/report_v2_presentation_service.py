"""將已驗證的 v2 報告整理成畫面所需的 context。"""

from .ai_report_preparation_service import (
    apply_report_sample_scope,
    replace_report_comment_refs_with_author_names,
    validate_report_source_facts,
)


def build_report_context(report, facts) -> dict:
    validate_report_source_facts(report, facts)
    report = replace_report_comment_refs_with_author_names(report, facts)
    report = apply_report_sample_scope(report)
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
        "page_title": "影片分析報告",
        "report": report, "facts": facts, "sentiment_rows": sentiment_rows,
        "sample_mode_detail": sample_mode_details[analysis_mode],
        "topic_panels": panels(report.topics, evidence_limit=3), "behavior_panels": panels(report.behavior_insights),
        "conclusion_panels": panels(report.conclusions),
        "show_behavior_section": analysis_mode != "small",
    }
