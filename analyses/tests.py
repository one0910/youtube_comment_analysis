from unittest.mock import patch

from .providers.youtube_provider import (
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)

from django.test import SimpleTestCase,TestCase #TestCase：每個測試之間隔離資料庫資料。
from django.urls import reverse #reverse()：透過 URL 名稱取得網址。
from .forms import NewAnalysisForm
from .services.youtube_url_parser import (
    InvalidYouTubeUrlError,
    get_video_id_from_youtube_url,
)
from .services.youtube_count_parser import (
    InvalidYouTubeCountTextError,
    convert_youtube_count_text_to_integer,
)

"""分析總覽頁面的基本測試。"""
class OverviewViewTests(TestCase): #這是Django 內建的測試指令。它會自動尋找 analyses/tests.py 內符合規則的測試：

    def test_overview_page_renders_expected_content(self):
        response = self.client.get(reverse("analyses:overview")) #模擬瀏覽器向 Django 發送請求。

        #確認首頁能正常開啟，不是 404 或 500。
        self.assertEqual(response.status_code, 200)

        #確認 View 使用正確的 Template。assertTemplateUsed:確認使用哪個 Template。
        self.assertTemplateUsed(response, "analyses/overview.html")

        #確認後端確實傳入四筆卡片資料。
        self.assertEqual(len(response.context["overview_stats"]), 4)

        #確認最後產生的 HTML 包含重要內容。assertContains:確認回傳的 HTML 是否包含指定文字。
        self.assertContains(response, "歡迎回來，創作者！")
        self.assertContains(response, "已分析影片")

"""新增分析頁面的基本測試。"""
class NewAnalysisViewTests(TestCase):
    def test_new_analysis_page_renders_expected_content(self):
        response = self.client.get(reverse("analyses:new_analysis"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "analyses/new_analysis.html")
        self.assertContains(response, "新增分析")
        self.assertContains(response, "YouTube 影片網址")

    def test_new_analysis_form_rejects_invalid_url(self):
        response = self.client.post(
            reverse("analyses:new_analysis"),
            {"input_video_url": "這不是網址"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertIsNone(response.context["validated_input_video_url"])

    @patch("analyses.views.get_video_preview_with_selenium")
    def test_new_analysis_form_accepts_supported_youtube_url(self,mock_get_video_preview_with_selenium):
        """有效 YouTube 網址應取得並傳入影片預覽資料。"""

        input_video_url = ("https://www.youtube.com/watch""?v=dQw4w9WgXcQ")
        expected_video_preview_data = YouTubeVideoPreviewData(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="測試影片標題",
            video_author_name="測試頻道",
            video_thumbnail_url=(
                "https://i.ytimg.com/vi/"
                "dQw4w9WgXcQ/hqdefault.jpg"
            ),
            video_view_count=123_456,
            video_comment_count=789,
        )

        mock_get_video_preview_with_selenium.return_value = (expected_video_preview_data)
        response = self.client.post(
            reverse("analyses:new_analysis"),
            {"input_video_url": input_video_url, },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].errors)
        self.assertEqual(response.context["validated_input_video_url"],input_video_url)
        self.assertEqual(response.context["youtube_video_id"],"dQw4w9WgXcQ")
        self.assertEqual(response.context["video_preview_data"],expected_video_preview_data,)
        self.assertContains(response,"測試影片標題")
        self.assertContains(response,"測試頻道")

        mock_get_video_preview_with_selenium.assert_called_once_with(youtube_video_id="dQw4w9WgXcQ")

    @patch("analyses.views.get_video_preview_with_selenium")
    def test_unavailable_youtube_video_renders_error_card(
        self,
        mock_get_video_preview_with_selenium,
    ):
        """YouTube 回覆影片不可用時，應顯示錯誤卡片而不是 500。"""
        mock_get_video_preview_with_selenium.side_effect = (
            YouTubeVideoUnavailableError(
                provider_status="ERROR",
                provider_reason="無法播放影片",
            )
        )

        response = self.client.post(
            reverse("analyses:new_analysis"),
            {"input_video_url": "https://www.youtube.com/watch?v=SbE675HRAIa"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["video_preview_data"])
        self.assertIsNotNone(response.context["video_preview_error"])
        self.assertContains(response, "找不到影片或影片無法存取")
        self.assertContains(response, "重新輸入")

    def test_htmx_invalid_url_returns_only_video_check_panel(self):
        """HTMX 驗證失敗時，只回傳表單區域及欄位錯誤。"""

        response = self.client.post(
            reverse("analyses:new_analysis"),
            {"input_video_url": "https://example.com/video/123"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response,"analyses/partials/video_check_panel.html")
        self.assertNotContains(response,"<!doctype html>")
        self.assertContains( response,"請輸入支援的 YouTube 影片網址。")



"""測試新增分析表單的資料驗證規則。"""
class NewAnalysisFormValidationTests(SimpleTestCase):
    def test_form_rejects_non_youtube_url(self):
        """格式正確但不是 YouTube 的網址，必須驗證失敗。"""

        # 直接建立 Form，不經過 View 或瀏覽器請求。
        form = NewAnalysisForm(
            data={
                "input_video_url": "https://example.com/video/123",
            }
        )

        # example.com 是合法 URL，但不是 YouTube，
        # 所以完整表單驗證必須失敗。
        self.assertFalse(form.is_valid())

        # 驗證錯誤必須出現在網址欄位。
        self.assertIn(
            "input_video_url",
            form.errors,
        )

class YouTubeCountParserTests(SimpleTestCase):
    """測試 YouTube 顯示數量的文字轉換。"""

    def test_supported_count_text_returns_integer(self):
        """常見的中文及英文數量格式應正確轉成整數。"""

        supported_count_examples = [
            ("2,313 則留言", 2_313),
            ("216萬次觀看", 2_160_000),
            ("1.2萬則留言", 12_000),
            ("1.2K comments", 1_200),
            ("2.5M views", 2_500_000),
            ("1.1億次觀看", 110_000_000),
        ]

        for (youtube_count_text,expected_count) in supported_count_examples:
            with self.subTest(youtube_count_text=youtube_count_text):
                actual_count = (
                    convert_youtube_count_text_to_integer( youtube_count_text)
                )

                self.assertEqual(actual_count,expected_count)

    def test_text_without_number_raises_error(self):
        """完全沒有數字的文字不能假裝成零。"""

        with self.assertRaises(InvalidYouTubeCountTextError):
            convert_youtube_count_text_to_integer("無法取得留言數")

"""測試 YouTube 網址解析功能。"""
class YouTubeUrlParserTests(SimpleTestCase):
    def test_supported_youtube_urls_return_video_id(self):
      expected_video_id = "dQw4w9WgXcQ"
      supported_urls = [
          "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
          "https://youtu.be/dQw4w9WgXcQ",
          "https://www.youtube.com/shorts/dQw4w9WgXcQ",
          "https://www.youtube.com/live/dQw4w9WgXcQ",
      ]

      for input_video_url in supported_urls:
          with self.subTest(input_video_url=input_video_url):
              actual_video_id = get_video_id_from_youtube_url(
                  input_video_url
              )

              self.assertEqual(actual_video_id, expected_video_id)

    def test_unsupported_urls_raise_error(self):
        unsupported_urls = [
            "這不是網址",
            "https://example.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=too-short",
            "https://www.youtube.com/channel/example",
        ]

        for input_video_url in unsupported_urls:
            with self.subTest(input_video_url=input_video_url):
                with self.assertRaises(InvalidYouTubeUrlError):
                    get_video_id_from_youtube_url(input_video_url)
