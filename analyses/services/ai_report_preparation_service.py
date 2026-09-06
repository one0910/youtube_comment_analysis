"""新版報告的純 Python 事實整理；不讀寫資料庫、不呼叫 AI、不裁切分析留言。"""

from collections import defaultdict
from dataclasses import dataclass

from analyses.providers.ai_analysis_provider import AIAnalysisRequest, AICommentInput
from analyses.providers.ai_report_v2 import (
    AIReportV2, DisplayNameActivityV2, RepeatedTextGroupV2, ReportSampleV2, ReportVideoV2,
)


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """保留完整 request，Top 5 僅為額外排名，並不是給 AI 的唯一輸入。"""

    request: AIAnalysisRequest
    video: ReportVideoV2
    sample: ReportSampleV2
    top_liked_comments: tuple[AICommentInput, ...]
    repeated_text_groups: tuple[RepeatedTextGroupV2, ...]
    display_name_activity: tuple[DisplayNameActivityV2, ...]
    unresolved_thread_comment_ids: tuple[str, ...]

    @property
    def displayed_comment_count_difference(self) -> int | None:
        displayed_count = self.video.displayed_comment_count
        return None if displayed_count is None else displayed_count - self.sample.analyzed_comment_count


def prepare_report_facts(
    analysis_request: AIAnalysisRequest, video: ReportVideoV2, *, sort_order: str, include_replies: bool,
) -> PreparedReportFacts:
    """輸入須已去重；遇到無效資料拒絕，不默默刪除留言或修猜數值。"""
    if not isinstance(analysis_request, AIAnalysisRequest) or not isinstance(video, ReportVideoV2):
        raise ValueError("必須提供分析 Request 與影片快照。")
    if video.youtube_video_id != analysis_request.youtube_video_id or video.title != analysis_request.video_title:
        raise ValueError("影片快照與分析輸入不一致。")
    comments = analysis_request.comments
    for comment in comments:
        _validate_comment(comment)
    sample = ReportSampleV2(
        analysis_request.comment_count, analysis_request.top_level_comment_count,
        analysis_request.reply_comment_count, sort_order, include_replies,
    )
    known_likes = (comment for comment in comments if comment.like_count is not None)
    top_comments = tuple(sorted(known_likes, key=lambda c: (-c.like_count, c.sequence, c.youtube_comment_id))[:5])
    activity, unresolved = _build_activity(comments)
    return PreparedReportFacts(
        request=analysis_request, video=video, sample=sample, top_liked_comments=top_comments,
        repeated_text_groups=_build_repeated_groups(comments), display_name_activity=activity,
        unresolved_thread_comment_ids=unresolved,
    )


def _validate_comment(comment: AICommentInput) -> None:
    if not isinstance(comment, AICommentInput):
        raise ValueError("留言必須是 AICommentInput。")
    if type(comment.sequence) is not int or comment.sequence < 1:
        raise ValueError("留言順序必須是正整數。")
    for value in (comment.youtube_comment_id, comment.author_display_name, comment.comment_text):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("留言 ID、顯示名稱與內容必須是非空文字。")
    parent = comment.parent_youtube_comment_id
    if parent is not None and (not isinstance(parent, str) or (parent and not parent.strip())):
        raise ValueError("父留言 ID 必須是文字、空字串或 None。")
    if comment.like_count is not None and (type(comment.like_count) is not int or comment.like_count < 0):
        raise ValueError("按讚數必須是非負整數或 None，不可猜測或轉型。")
    if type(comment.is_pinned) is not bool or not isinstance(comment.published_time_text, str):
        raise ValueError("留言置頂狀態或顯示時間格式不正確。")


def _build_repeated_groups(comments: tuple[AICommentInput, ...]) -> tuple[RepeatedTextGroupV2, ...]:
    by_text = defaultdict(list)
    for comment in comments:
        by_text[" ".join(comment.comment_text.split())].append(comment)
    return tuple(
        RepeatedTextGroupV2(
            normalized_text=text,
            author_display_names=tuple(dict.fromkeys(comment.author_display_name for comment in group)),
            comment_ids=tuple(comment.youtube_comment_id for comment in group),
        )
        for text, group in by_text.items() if len(group) >= 2
    )


def _build_activity(comments: tuple[AICommentInput, ...]) -> tuple[tuple[DisplayNameActivityV2, ...], tuple[str, ...]]:
    by_id = {comment.youtube_comment_id: comment for comment in comments}
    roots = {}

    def resolve_root(comment_id: str) -> str | None:
        # 迭代加快取，避免深層回覆造成 recursion error；缺父留言或循環不猜根節點。
        path = []
        seen = set()
        current = comment_id
        while current in by_id and current not in roots and current not in seen:
            seen.add(current)
            path.append(current)
            parent = by_id[current].parent_youtube_comment_id
            if not parent:
                roots[current] = current
                break
            current = parent
        root = roots.get(current)
        for visited_id in path:
            roots[visited_id] = root
        return root

    grouped = defaultdict(list)
    unresolved = []
    for comment in comments:
        root = resolve_root(comment.youtube_comment_id)
        if root is None:
            unresolved.append(comment.youtube_comment_id)
        else:
            grouped[(comment.author_display_name, root)].append(comment.youtube_comment_id)
    activity = tuple(
        DisplayNameActivityV2(name, root, tuple(ids))
        for (name, root), ids in grouped.items() if len(ids) >= 2
    )
    return activity, tuple(unresolved)


def validate_report_source_facts(report: AIReportV2, facts: PreparedReportFacts) -> None:
    """組裝報告後再次比對來源；此函式不判斷 AI 敘述的語意是否有充分證據。"""
    if report.video != facts.video or report.sample != facts.sample:
        raise ValueError("報告影片資訊或樣本統計與來源不一致。")
    expected_ids = tuple(comment.youtube_comment_id for comment in facts.top_liked_comments)
    if tuple(comment.youtube_comment_id for comment in report.top_liked_comments) != expected_ids:
        raise ValueError("高讚留言不是本次來源的 Top 5，或排序不正確。")
    for actual, source in zip(report.top_liked_comments, facts.top_liked_comments):
        if (actual.author_display_name, actual.comment_text, actual.like_count) != (
            source.author_display_name, source.comment_text, source.like_count,
        ):
            raise ValueError("高讚留言作者、原文或按讚數與來源不一致。")
    if report.repeated_text_groups != facts.repeated_text_groups:
        raise ValueError("重複文字群組與 Python 計算結果不一致。")
    if report.display_name_activity != facts.display_name_activity:
        raise ValueError("活躍發言紀錄與 Python 計算結果不一致。")
    source_ids = {comment.youtube_comment_id for comment in facts.request.comments}
    for item in (*report.topics, *report.conclusions, *report.behavior_insights, *report.risks, *report.recommendations):
        if not set(item.evidence_comment_ids).issubset(source_ids):
            raise ValueError("報告引用了不屬於本次輸入的留言 ID。")
