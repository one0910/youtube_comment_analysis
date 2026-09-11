from celery import shared_task

from .services.fetch_run_execution_service import execute_youtube_fetch_run_by_id
from .services.report_v2_execution_service import execute_report_v2_analysis_by_id, mark_report_v2_dispatch_failed


#@shared_task 是裝飾器。它把你定義的函式註冊、包裝成 Celery 任務，並透過 Celery 的任務物件提供
@shared_task(name="analyses.execute_youtube_fetch_run",queue="youtube_selenium",ignore_result=True)
# 任務task1:抓取留言並儲存
def execute_youtube_fetch_run_task(fetch_run_id: str) -> int:
    # 透過execute_youtube_fetch_run_by_id，雖然最後回傳留言數，但真正的重點是去進行抓留言、存資料、更新狀態，回傳留言數只是這次的工作摘要
    stored_comment_count = execute_youtube_fetch_run_by_id(fetch_run_id=fetch_run_id)
    print(f"""stored_comment_count => {stored_comment_count}""", )
    try:
        #留言儲存後，進行下一個任務task:進行deepseek AI分析及儲存
        execute_report_v2_analysis_task.delay(fetch_run_id=fetch_run_id)
    except Exception as error:
        mark_report_v2_dispatch_failed(fetch_run_id=fetch_run_id, error=error)
        raise
    return stored_comment_count


# 任務task2:讀取已儲存留言、呼叫 DeepSeek、驗證及儲存報告
@shared_task(name="analyses.execute_report_v2_analysis",queue="ai_analysis",ignore_result=True)
def execute_report_v2_analysis_task(fetch_run_id: str) -> str:
    analysis_result = execute_report_v2_analysis_by_id(fetch_run_id=fetch_run_id)
    return str(analysis_result.id)
