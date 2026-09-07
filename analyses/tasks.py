from celery import shared_task

from .services.fetch_run_execution_service import execute_youtube_fetch_run_by_id
from .services.report_v2_execution_service import execute_report_v2_analysis_by_id, mark_report_v2_dispatch_failed


"""在 Selenium 專用 Queue 執行指定的留言抓取紀錄。"""
@shared_task(name="analyses.execute_youtube_fetch_run",queue="youtube_selenium",ignore_result=True)
def execute_youtube_fetch_run_task(fetch_run_id: str) -> int:
    stored_comment_count = execute_youtube_fetch_run_by_id(fetch_run_id=fetch_run_id)
    try:
        execute_report_v2_analysis_task.delay(fetch_run_id=fetch_run_id)
    except Exception as error:
        mark_report_v2_dispatch_failed(fetch_run_id=fetch_run_id, error=error)
        raise
    return stored_comment_count


@shared_task(name="analyses.execute_report_v2_analysis",queue="ai_analysis",ignore_result=True)
def execute_report_v2_analysis_task(fetch_run_id: str) -> str:
    analysis_result = execute_report_v2_analysis_by_id(fetch_run_id=fetch_run_id)
    return str(analysis_result.id)
