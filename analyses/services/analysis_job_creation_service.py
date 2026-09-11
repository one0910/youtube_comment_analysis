from django.db import transaction
from analyses.models import AnalysisJob, FetchRun, Video
from analyses.providers.youtube_provider import YouTubeCommentFetchOptions


"""替指定影片建立一個等待處理的分析任務。"""
@transaction.atomic #@transaction.atomic表示這兩筆新增作業是一組：如果中途出錯，整組回滾，避免只建立其中一筆
def create_pending_analysis_job_for_video(
    video_record: Video,
    data_source: str = AnalysisJob.DataSource.SELENIUM, #用什麼工具抓？ 預設是selenium
    fetch_options: YouTubeCommentFetchOptions | None = None, #fetch_options是用來配置留言抓取的機制，例如用什麼順序抓留言、是否抓回覆、最多抓幾則
) -> AnalysisJob:
    fetch_options = fetch_options or YouTubeCommentFetchOptions()

    # 建立一個整份分析的工作單。也就是我要分析這支影片，請先幫我建立一張工作單，記錄這份分析的進度。
    analysis_job = AnalysisJob.objects.create(
        video=video_record,
        data_source=data_source
    )

    #建立「這次抓留言的作業紀錄」，也就是針對剛才那張分析工作單，建立第一次抓留言的紀錄，先記下要怎麼抓，以及目前的抓取狀態。
    FetchRun.objects.create(
        analysis_job=analysis_job,
        data_source=data_source,
        attempt_number=1,
        sort_order=fetch_options.sort_order.value,
        include_replies=fetch_options.include_replies,
        maximum_comment_count=fetch_options.maximum_comment_count,
    )

    return analysis_job
