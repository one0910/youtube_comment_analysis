from django.utils import timezone

from analyses.models import AnalysisJob, FetchRun
from analyses.providers.youtube_provider import (
    YouTubeCommentFetchOptions,
    YouTubeProvider,
)

from .youtube_fetch_service import fetch_and_store_youtube_comments


"""執行一次留言抓取，並保存任務的成功或失敗狀態。"""
def execute_youtube_fetch_run(
    fetch_run: FetchRun,
    youtube_provider: YouTubeProvider,
    fetch_options: YouTubeCommentFetchOptions | None = None,
) -> int:
    
    analysis_job = fetch_run.analysis_job
    started_at = timezone.now()

    analysis_job.status = AnalysisJob.Status.RUNNING
    analysis_job.started_at = analysis_job.started_at or started_at
    analysis_job.completed_at = None
    analysis_job.error_message = ""
    analysis_job.save(update_fields=["status", "started_at", "completed_at", "error_message", "updated_at"])

    fetch_run.status = FetchRun.Status.RUNNING
    fetch_run.started_at = started_at
    fetch_run.completed_at = None
    fetch_run.error_code = ""
    fetch_run.error_message = ""
    fetch_run.save(update_fields=["status", "started_at", "completed_at", "error_code", "error_message", "updated_at"])

    try:
        stored_comment_count = fetch_and_store_youtube_comments(
            fetch_run=fetch_run,
            youtube_provider=youtube_provider,
            fetch_options=fetch_options,
        )
    except Exception as error:
        completed_at = timezone.now()
        error_message = str(error)

        fetch_run.status = FetchRun.Status.FAILED
        fetch_run.completed_at = completed_at
        fetch_run.error_code = type(error).__name__
        fetch_run.error_message = error_message
        fetch_run.save(update_fields=["status", "completed_at", "error_code", "error_message", "updated_at"])

        analysis_job.status = AnalysisJob.Status.FAILED
        analysis_job.completed_at = completed_at
        analysis_job.error_message = error_message
        analysis_job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])

        raise

    completed_at = timezone.now()

    fetch_run.status = FetchRun.Status.COMPLETED
    fetch_run.fetched_comment_count = stored_comment_count
    fetch_run.completed_at = completed_at
    fetch_run.error_code = ""
    fetch_run.error_message = ""
    fetch_run.save(update_fields=["status", "fetched_comment_count", "completed_at", "error_code", "error_message", "updated_at"])

    analysis_job.status = AnalysisJob.Status.AWAITING_ANALYSIS
    analysis_job.completed_at = None
    analysis_job.error_message = ""
    analysis_job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])

    return stored_comment_count