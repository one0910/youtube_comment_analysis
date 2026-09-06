from analyses.models import FetchRun
from analyses.providers.ai_analysis_provider import (
    AIAnalysisRequest,
    AICommentInput,
)


"""指定的 FetchRun 尚無法提供 AI 分析資料。"""
class AIAnalysisInputUnavailableError(ValueError):


  """將一次抓取保存的留言快照轉成 AI Provider 輸入。"""
def build_ai_analysis_request_from_fetch_run(fetch_run: FetchRun) -> AIAnalysisRequest:

    if fetch_run.status != FetchRun.Status.COMPLETED:
        raise AIAnalysisInputUnavailableError("AI 分析只能使用已完成的留言抓取紀錄。")

    comment_observations = list(
        fetch_run.comment_observations
        .select_related("comment")
        .order_by("observed_at", "id")
    )

    if not comment_observations:
        raise AIAnalysisInputUnavailableError("找不到可供 AI 分析的留言快照。")

    comment_inputs = tuple(
        AICommentInput(
            sequence=comment_sequence,
            youtube_comment_id=(comment_observation.comment.youtube_comment_id),
            parent_youtube_comment_id=(comment_observation.comment.parent_youtube_comment_id or None),
            author_display_name=(comment_observation.observed_author_display_name),
            comment_text=(comment_observation.observed_comment_text),
            like_count=(comment_observation.observed_like_count),
            published_time_text=(comment_observation.observed_published_time_text),
            is_pinned=(comment_observation.observed_is_pinned),
        )
        for comment_sequence, comment_observation in enumerate( comment_observations,start=1)
    )

    video_record = fetch_run.analysis_job.video

    return AIAnalysisRequest(
        youtube_video_id=video_record.youtube_video_id,
        video_title=video_record.video_title,
        comments=comment_inputs,
    )
