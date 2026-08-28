from abc import ABC, abstractmethod #abc 是 Python 內建模組，全名是：Abstract Base Classes，用來建立一個「不能直接使用，只負責制定規格」的父類別。
from dataclasses import dataclass


@dataclass(frozen=True) #@dataclass是負責自動建立資料物件需要的方法，frozen=True 代表物件建立完成後，不允許重新修改欄位。
class YouTubeVideoPreviewData:
    """影片網址驗證成功後，顯示預覽卡片需要的資料。"""

    youtube_video_id: str
    video_title: str
    video_author_name: str | None
    video_thumbnail_url: str | None
    video_view_count: int | None
    video_comment_count: int | None


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

    @abstractmethod #強制實際 Provider 實作指定方法，所有繼承 YouTubeProvider 的子類別，都必須實作這個方法。
    def get_video_preview(self,youtube_video_id: str) -> YouTubeVideoPreviewData:
        """根據影片 ID 取得影片預覽資料。"""
        raise NotImplementedError