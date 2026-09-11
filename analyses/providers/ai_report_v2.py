"""正式影片分析報告使用的 V2 資料契約。"""

from dataclasses import dataclass, field
from datetime import datetime

from .ai_analysis_request import AIAnalysisMode


REPORT_SCHEMA_VERSION = "comment-analysis-result-v2"
SENTIMENT_METHOD = "ai_batch_estimate"
SENTIMENT_NOTICE = "AI 估計，非逐則分類統計；不代表整體民意。"
IDENTITY_NOTICE = "顯示名稱不等於唯一帳號，重複內容與活躍發言不能證明操作意圖。"


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必須是非空白文字。")


def _count(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}必須是非負整數。")


def _items(owner, name: str, item_type, *, required: bool = False) -> tuple:
    values = getattr(owner, name)
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name}必須是清單。")
    values = tuple(values)
    if required and not values:
        raise ValueError(f"{name}不可為空。")
    if any(not isinstance(value, item_type) for value in values):
        raise ValueError(f"{name}包含不正確的資料類型。")
    object.__setattr__(owner, name, values)
    return values


def _ids(owner, name: str, *, required: bool = True) -> tuple[str, ...]:
    values = _items(owner, name, str, required=required)
    for value in values:
        _text(value, name)
    if len(values) != len(set(values)):
        raise ValueError(f"{name}不可包含重複 ID。")
    return values


def _timestamp(value: str | None, label: str) -> None:
    if value is None:
        return
    _text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label}必須是 ISO 8601 時間。") from error
    if parsed.utcoffset() is None:
        raise ValueError(f"{label}必須包含時區。")


"""抓取時的影片快照；未知數值用 None，不能以 0 代替。"""
@dataclass(frozen=True, slots=True)
class ReportVideoV2:

    youtube_video_id: str
    title: str
    channel_name: str | None = None
    thumbnail_url: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    displayed_comment_count: int | None = None
    published_at: str | None = None
    duration_seconds: int | None = None
    captured_at: str | None = None

    def __post_init__(self):
        _text(self.youtube_video_id, "影片 ID")
        _text(self.title, "影片標題")
        for name in ("channel_name", "thumbnail_url"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        for name in ("view_count", "like_count", "displayed_comment_count", "duration_seconds"):
            if getattr(self, name) is not None:
                _count(getattr(self, name), name)
        _timestamp(self.published_at, "影片發布時間")
        _timestamp(self.captured_at, "快照時間")

"""有效、去重且實際送入 AI 的樣本；不宣稱已取得所有公開留言。"""
@dataclass(frozen=True, slots=True)
class ReportSampleV2:

    analyzed_comment_count: int
    top_level_comment_count: int
    reply_comment_count: int
    sort_order: str
    include_replies: bool
    analysis_mode: AIAnalysisMode = field(init=False)

    def __post_init__(self):
        for name in ("analyzed_comment_count", "top_level_comment_count", "reply_comment_count"):
            _count(getattr(self, name), name)
        if self.analyzed_comment_count < 1:
            raise ValueError("沒有有效留言時不建立 AI 報告。")
        if self.top_level_comment_count + self.reply_comment_count != self.analyzed_comment_count:
            raise ValueError("主留言數與回覆數總和必須等於分析留言數。")
        if self.sort_order not in ("newest", "top") or type(self.include_replies) is not bool:
            raise ValueError("抓取設定不正確。")
        if not self.include_replies and self.reply_comment_count:
            raise ValueError("不包含回覆時，回覆數必須為零。")
        count = self.analyzed_comment_count
        mode = AIAnalysisMode.SMALL if count < 30 else AIAnalysisMode.MEDIUM if count <= 200 else AIAnalysisMode.LARGE
        object.__setattr__(self, "analysis_mode", mode)


"""固定情緒類別下的估計百分比與解讀，不含留言筆數。"""
@dataclass(frozen=True, slots=True)
class SentimentCategoryV2:

    percentage: int
    description: str

    def __post_init__(self):
        _count(self.percentage, "情緒百分比")
        if self.percentage > 100:
            raise ValueError("情緒百分比不可超過 100。")
        _text(self.description, "情緒說明")


@dataclass(frozen=True, slots=True)
class SentimentEstimateV2:
    """30 則以上才可使用；總和 100 只表示比例一致，不代表精確測量。"""

    positive: SentimentCategoryV2
    neutral: SentimentCategoryV2
    negative: SentimentCategoryV2
    method: str = field(default=SENTIMENT_METHOD, init=False)
    notice: str = field(default=SENTIMENT_NOTICE, init=False)

    def __post_init__(self):
        categories = (self.positive, self.neutral, self.negative)
        if any(not isinstance(category, SentimentCategoryV2) for category in categories):
            raise ValueError("情緒類別格式不正確。")
        if sum(category.percentage for category in categories) != 100:
            raise ValueError("情緒估計百分比總和必須等於 100。")


@dataclass(frozen=True, slots=True)
class ReportTopicV2:
    name: str
    summary: str
    reasoning: str
    evidence_comment_ids: tuple[str, ...]

    def __post_init__(self):
        for name in ("name", "summary", "reasoning"):
            _text(getattr(self, name), name)
        _ids(self, "evidence_comment_ids")


@dataclass(frozen=True, slots=True)
class ReportInsightV2:
    """總結或行為解讀；新版 DeepSeek 輸出的每項解讀都必須有留言引用。"""

    title: str
    description: str
    evidence_comment_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.title, "洞察標題")
        _text(self.description, "洞察說明")
        _ids(self, "evidence_comment_ids", required=False)


@dataclass(frozen=True, slots=True)
class TopLikedCommentV2:
    """原文等事實由程式回填；AI 只提供 interpretation。未知讚數不列入 Top 5。"""

    youtube_comment_id: str
    author_display_name: str
    comment_text: str
    like_count: int
    interpretation: str

    def __post_init__(self):
        for name in ("youtube_comment_id", "author_display_name", "comment_text", "interpretation"):
            _text(getattr(self, name), name)
        _count(self.like_count, "按讚數")


@dataclass(frozen=True, slots=True)
class RepeatedTextGroupV2:
    """相同正規化文字，可跨顯示名稱；次數由唯一留言 ID 計算。"""

    normalized_text: str
    author_display_names: tuple[str, ...]
    comment_ids: tuple[str, ...]
    occurrence_count: int = field(init=False)

    def __post_init__(self):
        _text(self.normalized_text, "重複文字")
        _ids(self, "author_display_names")
        ids = _ids(self, "comment_ids")
        if len(ids) < 2 or len(self.author_display_names) > len(ids):
            raise ValueError("重複群組至少需要兩則留言，名稱數不可超過留言數。")
        object.__setattr__(self, "occurrence_count", len(ids))


@dataclass(frozen=True, slots=True)
class DisplayNameActivityV2:
    """同顯示名稱在同一討論串的多則發言；不等同同一真人或短時間洗版。"""

    author_display_name: str
    thread_youtube_comment_id: str
    comment_ids: tuple[str, ...]
    comment_count: int = field(init=False)

    def __post_init__(self):
        _text(self.author_display_name, "顯示名稱")
        _text(self.thread_youtube_comment_id, "討論串 ID")
        ids = _ids(self, "comment_ids")
        if len(ids) < 2:
            raise ValueError("活躍發言項目至少需要兩則留言。")
        object.__setattr__(self, "comment_count", len(ids))


@dataclass(frozen=True, slots=True)
class ReportProvenanceV2:
    provider_name: str
    model_name: str
    prompt_version: str
    generated_at: str
    source_label: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self):
        for name in ("provider_name", "model_name", "prompt_version", "generated_at"):
            _text(getattr(self, name), name)
        _timestamp(self.generated_at, "報告產生時間")
        if self.source_label is not None:
            _text(self.source_label, "資料來源標籤")
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if getattr(self, name) is not None:
                _count(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class AIReportV2:
    """程式與 AI 資料組裝後的報告，不是要求模型原樣產生的 API 回應。"""

    video: ReportVideoV2
    sample: ReportSampleV2
    provenance: ReportProvenanceV2
    overall_summary: str
    atmosphere: str
    sentiment: SentimentEstimateV2 | None
    topics: tuple[ReportTopicV2, ...]
    top_liked_comments: tuple[TopLikedCommentV2, ...]
    conclusions: tuple[ReportInsightV2, ...]
    limitations: tuple[str, ...]
    repeated_text_groups: tuple[RepeatedTextGroupV2, ...] = ()
    display_name_activity: tuple[DisplayNameActivityV2, ...] = ()
    behavior_insights: tuple[ReportInsightV2, ...] = ()
    schema_version: str = field(default=REPORT_SCHEMA_VERSION, init=False)
    identity_notice: str = field(default=IDENTITY_NOTICE, init=False)

    def __post_init__(self):
        for name, expected_type in (("video", ReportVideoV2), ("sample", ReportSampleV2),
                                    ("provenance", ReportProvenanceV2)):
            if not isinstance(getattr(self, name), expected_type):
                raise ValueError(f"{name}格式不正確。")
        _text(self.overall_summary, "整體摘要")
        _text(self.atmosphere, "整體氛圍")
        if self.sample.analysis_mode == AIAnalysisMode.SMALL:
            if self.sentiment is not None:
                raise ValueError("少於 30 則時只提供文字摘要，不提供情緒比例。")
        elif not isinstance(self.sentiment, SentimentEstimateV2):
            raise ValueError("30 則以上須提供情緒估計。")
        for name, item_type in (("topics", ReportTopicV2), ("top_liked_comments", TopLikedCommentV2),
                                 ("repeated_text_groups", RepeatedTextGroupV2),
                                 ("display_name_activity", DisplayNameActivityV2),
                                 ("conclusions", ReportInsightV2), ("behavior_insights", ReportInsightV2)):
            _items(self, name, item_type, required=name in ("topics", "conclusions"))
        for limitation in _items(self, "limitations", str, required=True):
            _text(limitation, "分析限制")
        top_ids = [comment.youtube_comment_id for comment in self.top_liked_comments]
        if len(top_ids) > min(5, self.sample.analyzed_comment_count) or len(set(top_ids)) != len(top_ids):
            raise ValueError("高讚留言最多五則，且不可重複或超過樣本數。")
        likes = [comment.like_count for comment in self.top_liked_comments]
        if likes != sorted(likes, reverse=True):
            raise ValueError("高讚留言必須依按讚數遞減排序。")
