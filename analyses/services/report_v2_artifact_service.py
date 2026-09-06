"""載入已驗證的 v2 Smoke Test 成品；不呼叫 API，也不寫入資料庫。"""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings

from analyses.providers.ai_analysis_provider import AIAnalysisRequest, AICommentInput
from analyses.providers.ai_report_v2 import (
    AIReportV2, DisplayNameActivityV2, IDENTITY_NOTICE, REPORT_SCHEMA_VERSION,
    SENTIMENT_METHOD, SENTIMENT_NOTICE, RepeatedTextGroupV2, ReportInsightV2,
    ReportProvenanceV2, ReportSampleV2, ReportTopicV2, ReportVideoV2,
    SentimentCategoryV2, SentimentEstimateV2, TopLikedCommentV2,
)
from .ai_report_preparation_service import prepare_report_facts, validate_report_source_facts


REAL_SOURCE_FILENAME = "tubesense_deepseek_comments_with_preview_20260904_151210_578363.json"
REAL_REPORT_FILENAME = "deepseek_report_v2_xtJBhAtpj1s_20260905_021050_749845.json"


def load_real_report_preview():
    """讀取固定的本機 Smoke Test 檔案，避免網址參數形成任意檔案讀取。"""
    directory = Path(settings.BASE_DIR) / "temporary"
    return load_report_v2_artifacts(directory / REAL_SOURCE_FILENAME, directory / REAL_REPORT_FILENAME)


def load_report_v2_artifacts(source_path: Path, report_path: Path):
    source = _read_json_object(source_path)
    report = load_report_v2_payload(_read_json_object(report_path))
    preview = _object(source, "preview")
    summary = _object(source, "fetch_summary")
    comments = tuple(
        AICommentInput(
            sequence=item["sequence"], youtube_comment_id=item["youtube_comment_id"],
            parent_youtube_comment_id=item["parent_youtube_comment_id"], author_display_name=item["author"],
            comment_text=item["comment_text"], like_count=item["like_count"],
            published_time_text=item["published_time_text"], is_pinned=item["is_pinned"],
        ) for item in _array(source, "comments")
    )
    request = AIAnalysisRequest(preview["youtube_video_id"], preview["video_title"], comments)
    video = ReportVideoV2(
        youtube_video_id=preview["youtube_video_id"], title=preview["video_title"],
        channel_name=preview.get("video_author_name"), thumbnail_url=preview.get("video_thumbnail_url"),
        view_count=preview.get("video_view_count"), like_count=preview.get("video_like_count"),
        displayed_comment_count=preview.get("video_comment_count"),
        captured_at=datetime.fromtimestamp(source_path.stat().st_mtime).astimezone().isoformat(),
    )
    facts = prepare_report_facts(
        request, video, sort_order=summary["sort_order"], include_replies=summary["include_replies"],
    )
    validate_report_source_facts(report, facts)
    return report, facts


def load_report_v2_payload(payload: dict) -> AIReportV2:
    """將已儲存 JSON 還原成受契約驗證的 DTO；衍生欄位不可被檔案竄改。"""
    _keys(payload, {
        "video", "sample", "provenance", "overall_summary", "atmosphere", "sentiment", "topics",
        "top_liked_comments", "repeated_text_groups", "display_name_activity", "behavior_insights",
        "conclusions", "risks", "recommendations", "limitations", "schema_version", "identity_notice",
    }, "report")
    if payload["schema_version"] != REPORT_SCHEMA_VERSION or payload["identity_notice"] != IDENTITY_NOTICE:
        raise ValueError("報告版本或身分提示不正確。")
    video_payload = _object(payload, "video")
    _keys(video_payload, {
        "youtube_video_id", "title", "channel_name", "thumbnail_url", "view_count", "like_count",
        "displayed_comment_count", "published_at", "duration_seconds", "captured_at",
    }, "video")
    video = ReportVideoV2(**video_payload)
    sample_payload = _object(payload, "sample")
    _keys(sample_payload, {
        "analyzed_comment_count", "top_level_comment_count", "reply_comment_count", "sort_order",
        "include_replies", "analysis_mode",
    }, "sample")
    stored_mode = sample_payload["analysis_mode"]
    sample = ReportSampleV2(**{key: value for key, value in sample_payload.items() if key != "analysis_mode"})
    if stored_mode != sample.analysis_mode.value:
        raise ValueError("樣本模式與留言數不一致。")
    provenance_payload = _object(payload, "provenance")
    _keys(provenance_payload, {
        "provider_name", "model_name", "prompt_version", "generated_at", "source_label",
        "prompt_tokens", "completion_tokens", "total_tokens",
    }, "provenance")
    return AIReportV2(
        video=video, sample=sample, provenance=ReportProvenanceV2(**provenance_payload),
        overall_summary=payload["overall_summary"], atmosphere=payload["atmosphere"],
        sentiment=_load_sentiment(payload["sentiment"]),
        topics=tuple(_load_topic(item) for item in _array(payload, "topics")),
        top_liked_comments=tuple(_load_top_comment(item) for item in _array(payload, "top_liked_comments")),
        repeated_text_groups=tuple(_load_repeated(item) for item in _array(payload, "repeated_text_groups")),
        display_name_activity=tuple(_load_activity(item) for item in _array(payload, "display_name_activity")),
        behavior_insights=tuple(_load_insight(item) for item in _array(payload, "behavior_insights")),
        conclusions=tuple(_load_insight(item) for item in _array(payload, "conclusions")),
        risks=tuple(_load_insight(item) for item in _array(payload, "risks")),
        recommendations=tuple(_load_insight(item) for item in _array(payload, "recommendations")),
        limitations=tuple(_array(payload, "limitations")),
    )


def _load_sentiment(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("sentiment 必須是物件或 null。")
    _keys(value, {"positive", "neutral", "negative", "method", "notice"}, "sentiment")
    if value["method"] != SENTIMENT_METHOD or value["notice"] != SENTIMENT_NOTICE:
        raise ValueError("情緒估算方式或提示不正確。")
    categories = {}
    for name in ("positive", "neutral", "negative"):
        item = _object(value, name)
        _keys(item, {"percentage", "description"}, f"sentiment.{name}")
        categories[name] = SentimentCategoryV2(**item)
    return SentimentEstimateV2(**categories)


def _load_topic(item):
    _keys(item, {"name", "summary", "reasoning", "evidence_comment_ids"}, "topic")
    return ReportTopicV2(**{**item, "evidence_comment_ids": _string_array(item, "evidence_comment_ids")})


def _load_top_comment(item):
    _keys(item, {"youtube_comment_id", "author_display_name", "comment_text", "like_count", "interpretation"}, "top comment")
    return TopLikedCommentV2(**item)


def _load_repeated(item):
    _keys(item, {"normalized_text", "author_display_names", "comment_ids", "occurrence_count"}, "repeated group")
    group = RepeatedTextGroupV2(
        item["normalized_text"], _string_array(item, "author_display_names"), _string_array(item, "comment_ids"),
    )
    if item["occurrence_count"] != group.occurrence_count:
        raise ValueError("重複文字次數與留言 ID 數不一致。")
    return group


def _load_activity(item):
    _keys(item, {"author_display_name", "thread_youtube_comment_id", "comment_ids", "comment_count"}, "activity")
    activity = DisplayNameActivityV2(
        item["author_display_name"], item["thread_youtube_comment_id"], _string_array(item, "comment_ids"),
    )
    if item["comment_count"] != activity.comment_count:
        raise ValueError("發言次數與留言 ID 數不一致。")
    return activity


def _load_insight(item):
    _keys(item, {"title", "description", "evidence_comment_ids"}, "insight")
    return ReportInsightV2(**{**item, "evidence_comment_ids": _string_array(item, "evidence_comment_ids")})


def _read_json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 頂層必須是 JSON object。")
    return value


def _object(owner: dict, key: str) -> dict:
    value = owner.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} 必須是 JSON object。")
    return value


def _array(owner: dict, key: str) -> list:
    value = owner.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} 必須是 JSON array。")
    return value


def _string_array(owner: dict, key: str) -> tuple[str, ...]:
    value = _array(owner, key)
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} 只能包含文字。")
    return tuple(value)


def _keys(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} 欄位不完整或包含未知欄位。")
