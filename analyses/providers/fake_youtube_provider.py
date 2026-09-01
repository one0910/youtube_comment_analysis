from collections.abc import Iterable, Iterator

from .youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)


"""使用固定測試資料模擬 YouTube Provider。"""
class FakeYouTubeProvider(YouTubeProvider):

    def __init__(
        self,
        video_preview_data: YouTubeVideoPreviewData,
        comment_data: Iterable[YouTubeCommentData],
    ):
        self._video_preview_data = video_preview_data
        self._comment_data = tuple(comment_data)

        for single_comment_data in self._comment_data:
            if (single_comment_data.youtube_video_id != video_preview_data.youtube_video_id):
                raise ValueError("Fake Provider 的留言與影片 ID 必須相同。")

    """回傳預先設定的影片資料。"""
    def get_video_preview(self, youtube_video_id: str ) -> YouTubeVideoPreviewData:
        self._validate_video_id(youtube_video_id=youtube_video_id)

        return self._video_preview_data

    def iter_video_comments(
        self,
        youtube_video_id: str,
        fetch_options: YouTubeCommentFetchOptions,
    ) -> Iterator[YouTubeCommentData]:
        """依照抓取選項逐筆回傳預先設定的留言。"""
        self._validate_video_id(youtube_video_id=youtube_video_id)
        selected_comment_data = list(self._comment_data)

        if not fetch_options.include_replies:
            selected_comment_data = [
                single_comment_data
                for single_comment_data in selected_comment_data
                if single_comment_data.parent_youtube_comment_id is None
            ]

        if fetch_options.sort_order == YouTubeCommentSortOrder.TOP:
            selected_comment_data.sort(
                key=lambda single_comment_data: (
                    single_comment_data.like_count
                    if single_comment_data.like_count is not None
                    else -1
                ),
                reverse=True,
            )
        else:
            selected_comment_data.sort(
                key=lambda single_comment_data: (
                    single_comment_data.published_at.timestamp()
                    if single_comment_data.published_at is not None
                    else float("-inf")
                ),
                reverse=True,
            )

        if fetch_options.maximum_comment_count is not None:
            selected_comment_data = selected_comment_data[:fetch_options.maximum_comment_count]

        yield from selected_comment_data

    def _validate_video_id(self, youtube_video_id: str) -> None:
        """確認呼叫時使用的是 Fake Provider 內設定的影片。"""

        if youtube_video_id != self._video_preview_data.youtube_video_id:
            raise YouTubeVideoUnavailableError(
                provider_status="VIDEO_NOT_FOUND",
                provider_reason="Fake Provider 找不到指定影片。",
            )