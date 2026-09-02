from dataclasses import dataclass
from enum import StrEnum

from django.utils.translation import gettext_lazy as _

from analyses.models import AnalysisJob


"""分析階段在畫面上的顯示狀態。"""
class AnalysisStageState(StrEnum):

    COMPLETED = "completed"
    CURRENT = "current"
    WAITING = "waiting"
    FAILED = "failed"
    CANCELLED = "cancelled"


"""提供給分析進度頁顯示的單一階段資料。"""
@dataclass(frozen=True, slots=True)
class AnalysisStagePresentation:

    number: int
    stage: AnalysisJob.Stage
    title: str
    description: str
    state: AnalysisStageState
    status_label: str


_STAGE_ORDER = (
    AnalysisJob.Stage.VIDEO_CONFIRMATION,
    AnalysisJob.Stage.COMMENT_FETCHING,
    AnalysisJob.Stage.COMMENT_NORMALIZATION,
    AnalysisJob.Stage.AI_ANALYSIS,
    AnalysisJob.Stage.REPORT_GENERATION,
)

_STAGE_DESCRIPTIONS = {
    AnalysisJob.Stage.VIDEO_CONFIRMATION: {
        AnalysisStageState.COMPLETED: _("影片基本資料已確認。"),
        AnalysisStageState.CURRENT: _("正在確認影片基本資料。"),
        AnalysisStageState.WAITING: _("等待確認影片基本資料。"),
    },
    AnalysisJob.Stage.COMMENT_FETCHING: {
        AnalysisStageState.COMPLETED: _("YouTube 留言抓取完成。"),
        AnalysisStageState.CURRENT: _("正在抓取 YouTube 留言。"),
        AnalysisStageState.WAITING: _("正在等待開始抓取 YouTube 留言。"),
    },
    AnalysisJob.Stage.COMMENT_NORMALIZATION: {
        AnalysisStageState.COMPLETED: _("留言資料已完成清理與正規化。"),
        AnalysisStageState.CURRENT: _("正在整理留言格式與父留言關係。"),
        AnalysisStageState.WAITING: _("將整理留言格式並建立可分析資料。"),
    },
    AnalysisJob.Stage.AI_ANALYSIS: {
        AnalysisStageState.COMPLETED: _("AI 情緒與主題分析已完成。"),
        AnalysisStageState.CURRENT: _("等待設定並開始 AI 情緒與主題分析。"),
        AnalysisStageState.WAITING: _("等待留言資料準備完成。"),
    },
    AnalysisJob.Stage.REPORT_GENERATION: {
        AnalysisStageState.COMPLETED: _("洞察報告已建立完成。"),
        AnalysisStageState.CURRENT: _("正在建立洞察報告。"),
        AnalysisStageState.WAITING: _("完成分析後將產生洞察報告。"),
    },
}


"""依任務狀態與目前階段建立五個畫面顯示項目。"""
def build_analysis_stage_presentations(analysis_job: AnalysisJob) -> list[AnalysisStagePresentation]:

    current_stage = AnalysisJob.Stage(analysis_job.current_stage)
    current_stage_index = _STAGE_ORDER.index(current_stage)
    stage_presentations = []

    for stage_index, stage in enumerate(_STAGE_ORDER):
        state = _get_stage_state(analysis_job=analysis_job, stage_index=stage_index, current_stage_index=current_stage_index)
        description = _get_stage_description(analysis_job=analysis_job, stage=stage, state=state)

        stage_presentations.append(
            AnalysisStagePresentation(
                number=stage_index + 1,
                stage=stage,
                title=str(stage.label),
                description=description,
                state=state,
                status_label=_get_stage_status_label(analysis_job=analysis_job, state=state),
            )
        )

    return stage_presentations


def _get_stage_state(analysis_job: AnalysisJob, stage_index: int, current_stage_index: int) -> AnalysisStageState:
    if analysis_job.status == AnalysisJob.Status.COMPLETED:
        return AnalysisStageState.COMPLETED

    if stage_index < current_stage_index:
        return AnalysisStageState.COMPLETED

    if stage_index > current_stage_index:
        return AnalysisStageState.WAITING

    if analysis_job.status == AnalysisJob.Status.FAILED:
        return AnalysisStageState.FAILED

    if analysis_job.status == AnalysisJob.Status.CANCELLED:
        return AnalysisStageState.CANCELLED

    return AnalysisStageState.CURRENT


def _get_stage_status_label(analysis_job: AnalysisJob, state: AnalysisStageState) -> str:
    if state == AnalysisStageState.COMPLETED:
        return str(_("已完成"))

    if state == AnalysisStageState.WAITING:
        return str(_("等待中"))

    if state == AnalysisStageState.FAILED:
        return str(_("失敗"))

    if state == AnalysisStageState.CANCELLED:
        return str(_("已取消"))

    if analysis_job.status == AnalysisJob.Status.PENDING:
        return str(_("準備中"))

    if analysis_job.status == AnalysisJob.Status.AWAITING_ANALYSIS:
        return str(_("等待中"))

    return str(_("進行中"))


def _get_stage_description(analysis_job: AnalysisJob, stage: AnalysisJob.Stage, state: AnalysisStageState) -> str:
    if state == AnalysisStageState.FAILED:
        return analysis_job.error_message or str(_("此階段執行失敗。"))

    if state == AnalysisStageState.CANCELLED:
        return str(_("此分析任務已取消。"))

    return str(_STAGE_DESCRIPTIONS[stage][state])