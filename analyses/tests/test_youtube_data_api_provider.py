from unittest.mock import call, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from analyses.models import AnalysisJob
from analyses.providers.selenium.youtube_provider import SeleniumYouTubeProvider
from analyses.providers.youtube_data_api.youtube_provider import YouTubeDataAPIProvider
from analyses.providers.youtube_provider import (
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeVideoUnavailableError,
)
from analyses.services.youtube.provider_factory import (
    YouTubeProviderUnavailableError,
    create_youtube_provider,
)


def build_comment_resource(comment_id: str, text: str, author_channel_id: str = "UC123"):
    return {
        "id": comment_id,
        "snippet": {
            "textOriginal": text,
            "authorDisplayName": "留言者",
            "authorChannelId": {"value": author_channel_id},
            "likeCount": 7,
            "publishedAt": "2026-09-18T01:02:03Z",
            "updatedAt": "2026-09-18T02:03:04Z",
        },
    }


class YouTubeDataAPIProviderTests(SimpleTestCase):
    def setUp(self):
        self.provider = YouTubeDataAPIProvider(api_key="test-api-key")

    def test_video_preview_maps_snippet_statistics_and_best_thumbnail(self):
        response = {
            "items": [{
                "snippet": {
                    "title": "API 測試影片",
                    "channelTitle": "測試頻道",
                    "thumbnails": {
                        "default": {"url": "https://example.com/default.jpg"},
                        "high": {"url": "https://example.com/high.jpg"},
                    },
                },
                "statistics": {
                    "viewCount": "123456",
                    "likeCount": "789",
                    "commentCount": "42",
                },
            }],
        }

        with patch.object(self.provider, "_request_json", return_value=response) as request_json:
            preview = self.provider.get_video_preview("dQw4w9WgXcQ")

        self.assertEqual(preview.youtube_video_id, "dQw4w9WgXcQ")
        self.assertEqual(preview.video_title, "API 測試影片")
        self.assertEqual(preview.video_author_name, "測試頻道")
        self.assertEqual(preview.video_thumbnail_url, "https://example.com/high.jpg")
        self.assertEqual(preview.video_view_count, 123456)
        self.assertEqual(preview.video_like_count, 789)
        self.assertEqual(preview.video_comment_count, 42)
        request_json.assert_called_once_with(
            "videos",
            part="snippet,statistics",
            id="dQw4w9WgXcQ",
            maxResults=1,
        )

    def test_missing_public_video_raises_unavailable_error(self):
        with patch.object(self.provider, "_request_json", return_value={"items": []}):
            with self.assertRaises(YouTubeVideoUnavailableError):
                self.provider.get_video_preview("dQw4w9WgXcQ")

    def test_comments_include_complete_replies_and_honor_total_limit(self):
        thread_response = {
            "items": [{
                "snippet": {
                    "topLevelComment": build_comment_resource("main-1", "主留言"),
                    "totalReplyCount": 2,
                },
            }],
            "nextPageToken": "unused-because-limit-reached",
        }
        replies_response = {
            "items": [
                build_comment_resource("reply-1", "回覆一"),
                build_comment_resource("reply-2", "回覆二"),
            ],
        }

        with patch.object(
            self.provider,
            "_request_json",
            side_effect=[thread_response, replies_response],
        ) as request_json:
            comments = list(self.provider.get_video_comments(
                "dQw4w9WgXcQ",
                YouTubeCommentFetchOptions(
                    sort_order=YouTubeCommentSortOrder.TOP,
                    include_replies=True,
                    maximum_comment_count=3,
                ),
            ))

        self.assertEqual([comment.youtube_comment_id for comment in comments], ["main-1", "reply-1", "reply-2"])
        self.assertIsNone(comments[0].parent_youtube_comment_id)
        self.assertEqual(comments[1].parent_youtube_comment_id, "main-1")
        self.assertEqual(comments[1].author_channel_url, "https://www.youtube.com/channel/UC123")
        self.assertEqual(comments[0].published_at.isoformat(), "2026-09-18T01:02:03+00:00")
        self.assertEqual(
            request_json.call_args_list,
            [
                call(
                    "commentThreads",
                    part="snippet",
                    videoId="dQw4w9WgXcQ",
                    maxResults=3,
                    order="relevance",
                    textFormat="plainText",
                ),
                call(
                    "comments",
                    part="snippet",
                    parentId="main-1",
                    maxResults=100,
                    textFormat="plainText",
                ),
            ],
        )

    def test_comments_paginate_and_can_skip_replies(self):
        first_page = {
            "items": [{
                "snippet": {
                    "topLevelComment": build_comment_resource("main-1", "第一則"),
                    "totalReplyCount": 5,
                },
            }],
            "nextPageToken": "page-2",
        }
        second_page = {
            "items": [{
                "snippet": {
                    "topLevelComment": build_comment_resource("main-2", "第二則"),
                    "totalReplyCount": 0,
                },
            }],
        }

        with patch.object(self.provider, "_request_json", side_effect=[first_page, second_page]) as request_json:
            comments = list(self.provider.get_video_comments(
                "dQw4w9WgXcQ",
                YouTubeCommentFetchOptions(include_replies=False),
            ))

        self.assertEqual([comment.youtube_comment_id for comment in comments], ["main-1", "main-2"])
        self.assertEqual(request_json.call_args_list[0].kwargs["order"], "time")
        self.assertEqual(request_json.call_args_list[1].kwargs["pageToken"], "page-2")


class YouTubeProviderFactoryTests(SimpleTestCase):
    @override_settings(YOUTUBE_API_KEY="")
    def test_api_provider_requires_key(self):
        with self.assertRaisesRegex(ImproperlyConfigured, "YOUTUBE_API_KEY"):
            YouTubeDataAPIProvider()

    @patch("analyses.services.youtube.provider_factory.SeleniumYouTubeProvider")
    def test_factory_keeps_selenium_available_for_local_development(self, provider_class):
        provider = create_youtube_provider(AnalysisJob.DataSource.SELENIUM)
        self.assertIs(provider, provider_class.return_value)

    @override_settings(YOUTUBE_API_KEY="test-api-key")
    def test_factory_creates_api_provider(self):
        provider = create_youtube_provider(AnalysisJob.DataSource.YOUTUBE_API)
        self.assertIsInstance(provider, YouTubeDataAPIProvider)

    def test_factory_rejects_unknown_source(self):
        with self.assertRaisesRegex(YouTubeProviderUnavailableError, "unknown"):
            create_youtube_provider("unknown")
