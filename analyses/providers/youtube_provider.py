from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class YouTubeCommentSortOrder(StrEnum):
    """YouTube 留言可使用的排序方式。"""

    TOP = "top"
    NEWEST = "newest"


@dataclass(frozen=True)
class YouTubeVideoPreviewData:
    """影片網址驗證成功後，顯示預覽卡片需要的資料。"""

    youtube_video_id: str
    video_title: str
    video_author_name: str | None
    video_thumbnail_url: str | None
    video_view_count: int | None
    video_comment_count: int | None
    video_like_count: int | None = None


@dataclass(frozen=True)
class YouTubeCommentData:
    """Provider 從 YouTube 取得的一則留言資料。"""

    youtube_comment_id: str
    youtube_video_id: str
    comment_text: str
    parent_youtube_comment_id: str | None = None
    author_display_name: str | None = None
    author_channel_id: str | None = None
    author_channel_url: str | None = None
    like_count: int | None = None
    published_at: datetime | None = None
    published_time_text: str | None = None
    youtube_updated_at: datetime | None = None
    is_pinned: bool = False


@dataclass(frozen=True)
class YouTubeCommentFetchOptions:
    """控制一次 YouTube 留言抓取的共用選項。"""

    sort_order: YouTubeCommentSortOrder = YouTubeCommentSortOrder.NEWEST
    include_replies: bool = True
    maximum_comment_count: int | None = None

    def __post_init__(self):
        """留言數量上限有設定時，必須至少為一。"""

        if (
            self.maximum_comment_count is not None
            and self.maximum_comment_count < 1
        ):
            raise ValueError("留言抓取數量上限必須至少為 1。")


class YouTubeVideoUnavailableError(Exception):
    """YouTube 回覆影片目前無法公開存取。"""

    def __init__(
        self,
        provider_status: str,
        provider_reason: str | None = None,
    ):
        self.provider_status = provider_status
        self.provider_reason = provider_reason

        error_message = (
            provider_reason
            or f"YouTube playability status: {provider_status}"
        )
        super().__init__(error_message)


class YouTubeProvider(ABC):
    """所有 YouTube 資料來源都必須遵守的共同介面。"""

    @abstractmethod
    def get_video_preview(self, youtube_video_id: str) -> YouTubeVideoPreviewData:
        """根據影片 ID 取得影片預覽資料。"""

        raise NotImplementedError

    @abstractmethod
    def iter_video_comments(
        self,
        youtube_video_id: str,
        fetch_options: YouTubeCommentFetchOptions,
        video_like_count: int | None = None
    ) -> Iterator[YouTubeCommentData]:
        """逐筆回傳指定影片的 YouTube 留言資料。"""

        raise NotImplementedError
