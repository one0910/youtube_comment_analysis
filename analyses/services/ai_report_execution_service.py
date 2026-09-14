from dataclasses import asdict
import json
from typing import Protocol
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from analyses.models import AnalysisJob, AnalysisResult, FetchRun
from analyses.providers.ai_analysis_request import AIAnalysisRequest
from analyses.providers.ai_report import AIReport, REPORT_SCHEMA_VERSION, ReportVideo
from analyses.providers.deepseek_report_provider import DeepSeekReportProvider

from .ai_analysis_request_service import build_ai_analysis_request_from_fetch_run
from .ai_report_preparation_service import create_validation_criteria, validate_report_source_facts


class ReportProvider(Protocol):
    def analyze_report(
        self,
        analysis_request: AIAnalysisRequest,
        video: ReportVideo,
        *,
        sort_order: str,
        include_replies: bool,
        source_label: str | None = None,
    ) -> AIReport: ...


"""依抓取紀錄 ID 讀取資料，建立、驗證並保存正式 報告。"""
def execute_report_analysis(fetch_run_id: UUID | str, provider: ReportProvider | None = None) -> AnalysisResult:
    # 取得指定的 FetchRun，以及它的分析任務和影片。
    fetch_run = FetchRun.objects.select_related("analysis_job", "analysis_job__video").get(pk=fetch_run_id)

    # 未傳入 Provider 時，就使用：DeepSeekReportProvider()
    if provider is None:
        provider = DeepSeekReportProvider()
    if fetch_run.status != FetchRun.Status.COMPLETED:
        # 建立一個要給deepseek AI分析的資料
        build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
    analysis_job = fetch_run.analysis_job
    # 將任務標記為正在 AI 分析
    analysis_job.status = AnalysisJob.Status.RUNNING
    analysis_job.current_stage = AnalysisJob.Stage.AI_ANALYSIS
    analysis_job.progress_percentage = 75 #這裡的 75 是程式設定的階段進度，不是 DeepSeek 回報「已算完 75%」
    analysis_job.completed_at = None
    analysis_job.error_message = ""
    analysis_job.save(update_fields=[
        "status", "current_stage", "progress_percentage", "completed_at", "error_message", "updated_at",
    ])

    try:
        # 準備留言與影片資料
        # 建立一個要給deepseek AI分析的資料，它裡面有留言數、主留言數、回覆留言數、影片title、影片id以及所有留言資料
        analysis_request = build_ai_analysis_request_from_fetch_run(fetch_run=fetch_run)
        report_video = build_report_video_from_fetch_run(fetch_run=fetch_run)

        # 開始把資料送進DeepSeek Provider，這裡會呼叫 DeepSeek API、解析回應，並將 AI 的文字分析與 Python 計算的資料組裝成 AIReport的格式
        ai_report = provider.analyze_report(
            analysis_request,
            report_video,
            sort_order=fetch_run.sort_order,
            include_replies=fetch_run.include_replies,
            source_label=f"analysis-job:{analysis_job.id}/fetch-run:{fetch_run.id}",
        )

        '''
        這裡的create_validation_criteria目的是將影片資訊、所有留言做一個整理及正規化，除了原本的留言及影片資訊外、
            1.還會輸出 sample，也就是留言總數、主留言數、回覆數、抓取選項與樣本模式
            2.還會輸出 top_liked_comments，也就是已知按讚數的留言中，排名最高的至多 5 則
            3.還會輸出 repeated_text_groups，整理空白後，文字相同的留言群組
            4.還會輸出 display_name_activity，同一顯示名稱在同一討論串的多次發言
            5.還會輸出 unresolved_thread_comment_ids，無法確認所屬根討論串的留言 ID
        '''
        validation_criteria = create_validation_criteria(
            analysis_request,
            report_video,
            sort_order=fetch_run.sort_order,
            include_replies=fetch_run.include_replies,
        )

        '''
        這裡的validate_report_source_facts目的是核對Deepseek所產的報告有沒有偏離來源，也就是它會與facts做核對，目前會檢查的有:
            1.影片資訊、樣本統計是否一致
            2.高讚留言是否真的是來源的 Top 5，排序是否一致。
            3.高讚留言的作者、原文、按讚數是否被改動
            4.活躍發言紀錄是否一致
            5.議題、結論等引用的留言 ID，是否存在於本次輸入
        驗證成功時，它回傳的是 None，程式以「沒有拋出例外」代表檢查通過。
        '''
        validate_report_source_facts(ai_report, validation_criteria)
        # 儲存報告並
        return _save_report_result(fetch_run=fetch_run, report=ai_report)
    except Exception as error:
        mark_report_analysis_failed(analysis_job=analysis_job, error=error)
        raise


"""把資料庫中的影片資料轉成會永久保存於報告內的快照。"""
def build_report_video_from_fetch_run(fetch_run: FetchRun) -> ReportVideo:
    video = fetch_run.analysis_job.video
    captured_at = fetch_run.completed_at or timezone.now()
    return ReportVideo(
        youtube_video_id=video.youtube_video_id,
        title=video.video_title,
        channel_name=video.video_author_name or None,
        thumbnail_url=video.video_thumbnail_url or None,
        view_count=video.video_view_count,
        like_count=video.video_like_count,
        displayed_comment_count=video.video_comment_count,
        captured_at=captured_at.isoformat(),
    )


@transaction.atomic
def _save_report_result(fetch_run: FetchRun, report: AIReport) -> AnalysisResult:
    analysis_job = AnalysisJob.objects.select_for_update().get(pk=fetch_run.analysis_job_id)
    latest_attempt = analysis_job.analysis_results.aggregate(number=Max("attempt_number"))["number"] or 0
    provenance = report.provenance
    result = AnalysisResult(
        analysis_job=analysis_job,
        source_fetch_run=fetch_run,
        attempt_number=latest_attempt + 1,
        provider_name=provenance.provider_name,
        model_name=provenance.model_name,
        prompt_version=provenance.prompt_version,
        schema_version=REPORT_SCHEMA_VERSION,
        analysis_mode=report.sample.analysis_mode.value,
        analyzed_comment_count=report.sample.analyzed_comment_count,
        main_comment_count=report.sample.main_comment_count,
        reply_comment_count=report.sample.reply_comment_count,
        result_data=json.loads(json.dumps(asdict(report), ensure_ascii=False)),
        prompt_tokens=provenance.prompt_tokens,
        completion_tokens=provenance.completion_tokens,
        total_tokens=provenance.total_tokens,
    )
    result.full_clean()
    result.save()

    analysis_job.status = AnalysisJob.Status.COMPLETED
    analysis_job.current_stage = AnalysisJob.Stage.REPORT_GENERATION
    analysis_job.progress_percentage = 100
    analysis_job.completed_at = timezone.now()
    analysis_job.error_message = ""
    analysis_job.save(update_fields=[
        "status", "current_stage", "progress_percentage", "completed_at", "error_message", "updated_at",
    ])
    return result


def mark_report_analysis_failed(analysis_job: AnalysisJob, error: Exception) -> None:
    analysis_job.status = AnalysisJob.Status.FAILED
    analysis_job.current_stage = AnalysisJob.Stage.AI_ANALYSIS
    analysis_job.completed_at = timezone.now()
    analysis_job.error_message = str(error)
    analysis_job.save(update_fields=["status", "current_stage", "completed_at", "error_message", "updated_at"])


def mark_report_dispatch_failed(fetch_run_id: UUID | str, error: Exception) -> None:
    fetch_run = FetchRun.objects.select_related("analysis_job").get(pk=fetch_run_id)
    mark_report_analysis_failed(analysis_job=fetch_run.analysis_job, error=error)
