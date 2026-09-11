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
    PENDING = "pending" 
    AWAITING_ANALYSIS = "awaiting_analysis" 


"""提供給分析進度頁顯示的單一階段資料。"""
@dataclass(frozen=True, slots=True)
class AnalysisStagePresentation:

    number: int
    stage: AnalysisJob.Stage
    title: str
    description: str
    state: AnalysisStageState
    status_label: str


# 這裡先定義在分析進度的頁面中，有哪些分析階段也用於顯示於前端的文字
_STAGE_ORDER = (
    AnalysisJob.Stage.VIDEO_CONFIRMATION, #確認影片資料
    AnalysisJob.Stage.COMMENT_FETCHING, #抓取留言
    AnalysisJob.Stage.COMMENT_NORMALIZATION, #留言清理與正規化
    AnalysisJob.Stage.AI_ANALYSIS, #AI 情緒與主題分析
    AnalysisJob.Stage.REPORT_GENERATION, #建立洞察報告
)

#承上，每個階段下面都有目前狀態的相關描述，一樣也是用來顯示於前端
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
    # 從分析任務物件取得目前階段，轉成 Stage 列舉
    current_stage = AnalysisJob.Stage(analysis_job.current_stage)
    # 然後確認該階段的_STAGE_ORDER的index位置
    current_stage_index = _STAGE_ORDER.index(current_stage)
    stage_presentations = []

    # 遍歷5個分析階段
    for stage_index, stage in enumerate(_STAGE_ORDER): #enumerate()這個函式可以依序拿到索引和階段
        # 透過_get_stage_state來取得該階段的目前狀態，例如completed、current、waiting
        state = _get_stage_state(analysis_job=analysis_job, stage_index=stage_index, current_stage_index=current_stage_index)
        # 透過_get_stage_description將該該目前目前的狀態轉換成要顯示的文字，例如COMPLETED就是影片基本資料已確認
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


# 判斷該階段應是什麼狀態，例如1.確認影片資料的"已完成"或"等待中"
def _get_stage_state(analysis_job: AnalysisJob, stage_index: int, current_stage_index: int) -> AnalysisStageState:
    # 若分析階段目前的狀態是"完成"(completed) ，則回傳"完成"(completed)。
    if analysis_job.status == AnalysisJob.Status.COMPLETED:
        return AnalysisStageState.COMPLETED

    #若目前階段大於
    if stage_index < current_stage_index:
        return AnalysisStageState.COMPLETED

    if stage_index > current_stage_index:
        return AnalysisStageState.WAITING

    if analysis_job.status == AnalysisJob.Status.FAILED:
        return AnalysisStageState.FAILED

    if analysis_job.status == AnalysisJob.Status.CANCELLED:
        return AnalysisStageState.CANCELLED

    return AnalysisStageState.CURRENT

# 每個階段的標題旁邊的小tag，會顯示目前正在進行的狀態顥示，例如等待中、已完成
def _get_stage_status_label(analysis_job: AnalysisJob, state: AnalysisStageState) -> str:
    if state == AnalysisStageState.COMPLETED:
        return str(_("已完成"))

    if state == AnalysisStageState.WAITING:
        return str(_("等待中"))

    if state == AnalysisStageState.FAILED:
        return str(_("失敗"))

    if state == AnalysisStageState.CANCELLED:
        return str(_("已取消"))
    
    if state == AnalysisStageState.CURRENT:
        return str(_("目前處理中..."))
      
    if analysis_job.status == AnalysisJob.Status.PENDING:
        return str(_("等待處理"))

    if analysis_job.status == AnalysisJob.Status.AWAITING_ANALYSIS:
        return str(_("等待 AI 分析"))

    return str(_("進行中"))


# 每個階段的標題下面的狀態文字描述，例如"正在抓取YouTube留言"、"正在確認影片基本資料"
def _get_stage_description(analysis_job: AnalysisJob, stage: AnalysisJob.Stage, state: AnalysisStageState) -> str:
    if state == AnalysisStageState.FAILED:
        return analysis_job.error_message or str(_("此階段執行失敗。"))

    if state == AnalysisStageState.CANCELLED:
        return str(_("此分析任務已取消。"))

    return str(_STAGE_DESCRIPTIONS[stage][state])