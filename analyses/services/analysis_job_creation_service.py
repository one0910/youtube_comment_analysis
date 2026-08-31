from analyses.models import AnalysisJob, Video


"""替指定影片建立一個等待處理的分析任務。"""
def create_pending_analysis_job_for_video(
    video_record: Video,
    data_source: str = AnalysisJob.DataSource.SELENIUM,
) -> AnalysisJob:
    
    analysis_job = AnalysisJob.objects.create(video=video_record,data_source=data_source)

    return analysis_job