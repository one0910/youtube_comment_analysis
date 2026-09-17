import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from ..youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)


YOUTUBE_DATA_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_DATA_API_TIMEOUT_SECONDS = 30
YOUTUBE_DATA_API_PAGE_SIZE = 100


class YouTubeDataAPIError(RuntimeError):
    """YouTube Data API 無法完成請求。"""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        self.provider_message = message
        super().__init__(message or reason)


def _parse_youtube_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_non_negative_integer(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


class YouTubeDataAPIProvider(YouTubeProvider):
    """使用 YouTube Data API v3 取得公開影片與留言資料。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or settings.YOUTUBE_API_KEY).strip()
        if not self.api_key:
            raise ImproperlyConfigured("使用 YouTube API 時必須設定 YOUTUBE_API_KEY。")

    def _request_json(self, resource: str, **parameters: Any) -> dict[str, Any]:
        query_parameters = {**parameters, "key": self.api_key}
        request_url = f"{YOUTUBE_DATA_API_BASE_URL}/{resource}?{urlencode(query_parameters)}"
        request = Request(request_url, headers={"Accept": "application/json"})

        try:
            with urlopen(request, timeout=YOUTUBE_DATA_API_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except HTTPError as error:
            reason = f"http_{error.code}"
            message = "YouTube Data API 請求失敗。"
            try:
                error_payload = json.loads(error.read().decode("utf-8"))
                provider_error = error_payload.get("error", {})
                error_details = provider_error.get("errors") or []
                if error_details:
                    reason = error_details[0].get("reason") or reason
                message = provider_error.get("message") or message
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            # HTTPError 內含帶有 API Key 的完整 URL，不可作為例外鏈輸出。
            raise YouTubeDataAPIError(reason=reason, message=message) from None
        except (URLError, TimeoutError) as error:
            # 不把原始 URL 放入錯誤訊息，避免 API Key 被寫入日誌。
            raise YouTubeDataAPIError(
                reason="network_error",
                message="無法連線到 YouTube Data API。",
            ) from None

    def get_video_preview(self, youtube_video_id: str) -> YouTubeVideoPreviewData:
        payload = self._request_json(
            "videos",
            part="snippet,statistics",
            id=youtube_video_id,
            maxResults=1,
        )
        items = payload.get("items") or []
        if not items:
            raise YouTubeVideoUnavailableError(
                provider_status="NOT_FOUND",
                provider_reason="YouTube API 找不到這部公開影片。",
            )

        item = items[0]
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = next(
            (
                thumbnails[name].get("url")
                for name in ("maxres", "standard", "high", "medium", "default")
                if thumbnails.get(name, {}).get("url")
            ),
            None,
        )

        return YouTubeVideoPreviewData(
            youtube_video_id=youtube_video_id,
            video_title=snippet.get("title") or youtube_video_id,
            video_author_name=snippet.get("channelTitle"),
            video_thumbnail_url=thumbnail_url,
            video_view_count=_optional_non_negative_integer(statistics.get("viewCount")),
            video_like_count=_optional_non_negative_integer(statistics.get("likeCount")),
            video_comment_count=_optional_non_negative_integer(statistics.get("commentCount")),
        )

    def _build_comment_data(
        self,
        *,
        youtube_video_id: str,
        comment_resource: dict[str, Any],
        parent_youtube_comment_id: str | None,
    ) -> YouTubeCommentData:
        snippet = comment_resource.get("snippet", {})
        author_channel_id_data = snippet.get("authorChannelId") or {}
        author_channel_id = author_channel_id_data.get("value")

        return YouTubeCommentData(
            youtube_comment_id=comment_resource["id"],
            youtube_video_id=youtube_video_id,
            comment_text=snippet.get("textOriginal") or snippet.get("textDisplay") or "",
            parent_youtube_comment_id=parent_youtube_comment_id,
            author_display_name=snippet.get("authorDisplayName"),
            author_channel_id=author_channel_id,
            author_channel_url=(
                f"https://www.youtube.com/channel/{author_channel_id}"
                if author_channel_id
                else None
            ),
            like_count=_optional_non_negative_integer(snippet.get("likeCount")),
            published_at=_parse_youtube_datetime(snippet.get("publishedAt")),
            youtube_updated_at=_parse_youtube_datetime(snippet.get("updatedAt")),
            is_pinned=False,
        )

    def _iter_replies(
        self,
        *,
        youtube_video_id: str,
        parent_youtube_comment_id: str,
    ) -> Iterator[YouTubeCommentData]:
        page_token: str | None = None
        while True:
            parameters: dict[str, Any] = {
                "part": "snippet",
                "parentId": parent_youtube_comment_id,
                "maxResults": YOUTUBE_DATA_API_PAGE_SIZE,
                "textFormat": "plainText",
            }
            if page_token:
                parameters["pageToken"] = page_token

            payload = self._request_json("comments", **parameters)
            for reply_resource in payload.get("items") or []:
                yield self._build_comment_data(
                    youtube_video_id=youtube_video_id,
                    comment_resource=reply_resource,
                    parent_youtube_comment_id=parent_youtube_comment_id,
                )

            page_token = payload.get("nextPageToken")
            if not page_token:
                return

    def get_video_comments(
        self,
        youtube_video_id: str,
        fetch_options: YouTubeCommentFetchOptions,
    ) -> Iterator[YouTubeCommentData]:
        maximum_comment_count = fetch_options.maximum_comment_count
        yielded_comment_count = 0
        page_token: str | None = None
        api_order = (
            "relevance"
            if fetch_options.sort_order == YouTubeCommentSortOrder.TOP
            else "time"
        )

        while maximum_comment_count is None or yielded_comment_count < maximum_comment_count:
            remaining_count = (
                YOUTUBE_DATA_API_PAGE_SIZE
                if maximum_comment_count is None
                else min(YOUTUBE_DATA_API_PAGE_SIZE, maximum_comment_count - yielded_comment_count)
            )
            parameters: dict[str, Any] = {
                "part": "snippet",
                "videoId": youtube_video_id,
                "maxResults": remaining_count,
                "order": api_order,
                "textFormat": "plainText",
            }
            if page_token:
                parameters["pageToken"] = page_token

            payload = self._request_json("commentThreads", **parameters)
            for thread_resource in payload.get("items") or []:
                thread_snippet = thread_resource.get("snippet", {})
                top_level_comment = thread_snippet.get("topLevelComment")
                if not top_level_comment:
                    continue

                top_level_comment_id = top_level_comment["id"]
                yield self._build_comment_data(
                    youtube_video_id=youtube_video_id,
                    comment_resource=top_level_comment,
                    parent_youtube_comment_id=None,
                )
                yielded_comment_count += 1
                if maximum_comment_count is not None and yielded_comment_count >= maximum_comment_count:
                    return

                if fetch_options.include_replies and int(thread_snippet.get("totalReplyCount") or 0) > 0:
                    for reply_data in self._iter_replies(
                        youtube_video_id=youtube_video_id,
                        parent_youtube_comment_id=top_level_comment_id,
                    ):
                        yield reply_data
                        yielded_comment_count += 1
                        if maximum_comment_count is not None and yielded_comment_count >= maximum_comment_count:
                            return

            page_token = payload.get("nextPageToken")
            if not page_token:
                return
