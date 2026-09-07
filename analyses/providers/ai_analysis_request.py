"""正式 AI 報告流程共用的分析模式與輸入資料契約。"""

from dataclasses import dataclass
from enum import StrEnum


class AIAnalysisMode(StrEnum):
    """依有效留言數量決定分析報告的詳細程度。"""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass(frozen=True, slots=True)
class AICommentInput:
    """提供給 AI 分析的一則留言快照。"""

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


@dataclass(frozen=True, slots=True)
class AIAnalysisRequest:
    """一次 AI 留言分析所需要的影片與留言資料。"""

    youtube_video_id: str
    video_title: str
    comments: tuple[AICommentInput, ...]

    def __post_init__(self):
        object.__setattr__(self, "comments", tuple(self.comments))
        comment_ids = [comment.youtube_comment_id for comment in self.comments]
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
