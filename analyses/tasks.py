from celery import shared_task

from .providers.youtube_provider import YouTubeCommentFetchOptions
from .services.fetch_run_execution_service import execute_youtube_fetch_run_by_id


"""在 Selenium 專用 Queue 執行指定的留言抓取紀錄。"""
@shared_task(name="analyses.execute_youtube_fetch_run",queue="youtube_selenium",ignore_result=True)
def execute_youtube_fetch_run_task(fetch_run_id: str,maximum_comment_count: int | None = None) -> int:

    fetch_options = YouTubeCommentFetchOptions(maximum_comment_count=maximum_comment_count)
    return execute_youtube_fetch_run_by_id(fetch_run_id=fetch_run_id,fetch_options=fetch_options)
