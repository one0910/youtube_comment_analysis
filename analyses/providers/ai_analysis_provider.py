from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


"""依有效留言數量決定分析報告的詳細程度。"""
class AIAnalysisMode(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


"""提供給 AI 分析的一則留言快照。"""
@dataclass(frozen=True, slots=True)
class AICommentInput:
    sequence: int
    youtube_comment_id: str
    parent_youtube_comment_id: str | None
    author_display_name: str
    comment_text: str
    like_count: int | None
    published_time_text: str
    is_pinned: bool

    def __post_init__(self):
        if self.sequence < 1:
            raise ValueError("留言順序必須至少為 1。")

        if not self.youtube_comment_id.strip():
            raise ValueError("YouTube 留言 ID 不可為空白。")

        if not self.comment_text.strip():
            raise ValueError("留言內容不可為空白。")


"""一次 AI 留言分析所需要的影片與留言資料。"""
@dataclass(frozen=True, slots=True)
class AIAnalysisRequest:
    youtube_video_id: str
    video_title: str
    comments: tuple[AICommentInput, ...]

    def __post_init__(self):
        object.__setattr__(self,"comments", tuple(self.comments))

        comment_ids = [ comment.youtube_comment_id for comment in self.comments ]

        if len(comment_ids) != len(set(comment_ids)):
            raise ValueError("AI 分析輸入不可包含重複的留言 ID。")

    @property
    def comment_count(self) -> int:
        return len(self.comments)

    @property
    def top_level_comment_count(self) -> int:
        return sum(not comment.parent_youtube_comment_id for comment in self.comments)

    @property
    def reply_comment_count(self) -> int:
        return sum(bool(comment.parent_youtube_comment_id) for comment in self.comments)


"""AI 對留言區整體情緒分布的分析結果。"""
@dataclass(frozen=True, slots=True)
class SentimentDistribution:
    positive_percentage: int
    neutral_percentage: int
    negative_percentage: int
    overview: str

    def __post_init__(self):
        percentages = (self.positive_percentage,self.neutral_percentage,self.negative_percentage)
        if any(percentage < 0 or percentage > 100 for percentage in percentages):
            raise ValueError("情緒百分比必須介於 0 到 100。")

        if sum(percentages) != 100:
            raise ValueError("情緒百分比總和必須等於 100。")


"""留言區中的一個主要討論議題。"""
@dataclass(frozen=True, slots=True)
class AnalysisTopic:
    name: str
    summary: str
    evidence_comment_ids: tuple[str, ...] = field(default_factory=tuple)


"""用於報告中的高讚數或具代表性留言。"""
@dataclass(frozen=True, slots=True)
class RepresentativeComment:
    youtube_comment_id: str
    author_display_name: str
    like_count: int | None
    excerpt: str
    interpretation: str


"""由分析流程發現的重複發言現象。"""
@dataclass(frozen=True, slots=True)
class RepeatedContentFinding:
    author_display_name: str
    repeated_text: str
    occurrence_count: int
    comment_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.occurrence_count < 1:
            raise ValueError("重複發言次數必須至少為 1。")

        if self.occurrence_count != len(self.comment_ids):
            raise ValueError("重複發言次數必須與留言 ID 數量一致。")

"""AI 分析完成後供資料庫與報告頁使用的結構化資料。"""
@dataclass(frozen=True, slots=True)
class AIAnalysisReportData:
    analysis_mode: AIAnalysisMode
    analyzed_comment_count: int
    top_level_comment_count: int
    reply_comment_count: int
    overall_summary: str
    sentiment: SentimentDistribution | None
    topics: tuple[AnalysisTopic, ...] = field(default_factory=tuple)
    representative_comments: tuple[ RepresentativeComment,...] = field(default_factory=tuple)
    repeated_content_findings: tuple[RepeatedContentFinding,... ]= field(default_factory=tuple)
    risk_points: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.analyzed_comment_count < 0:
            raise ValueError("分析留言數不可小於 0。")

        if (self.top_level_comment_count + self.reply_comment_count!= self.analyzed_comment_count):
            raise ValueError("主留言數與回覆數的總和必須等於分析留言數。")

"""AI Provider 回報的 Token 使用量。"""
@dataclass(frozen=True, slots=True)
class AIProviderUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


"""AI Provider 的完整回應與追蹤資訊。"""
@dataclass(frozen=True, slots=True)
class AIProviderResponse:
    provider_name: str
    model_name: str
    prompt_version: str
    report: AIAnalysisReportData
    usage: AIProviderUsage


"""所有 AI 留言分析供應商必須遵守的共同介面。"""
class AIAnalysisProvider(ABC):
    """分析指定影片的留言並回傳結構化結果。"""
    @abstractmethod
    def analyze_comments(self,analysis_request: AIAnalysisRequest) -> AIProviderResponse:
        raise NotImplementedError