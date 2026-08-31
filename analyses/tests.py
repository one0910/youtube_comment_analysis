import uuid
from unittest.mock import MagicMock, patch

from .providers.youtube_provider import (
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)

from django.test import SimpleTestCase,TestCase #TestCase：每個測試之間隔離資料庫資料。
from django.urls import reverse #reverse()：透過 URL 名稱取得網址。
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from .forms import NewAnalysisForm
from .models import AnalysisJob, Video
from .services.youtube_url_parser import (
    InvalidYouTubeUrlError,
    get_video_id_from_youtube_url,
)
from .services.youtube_count_parser import (
    InvalidYouTubeCountTextError,
    convert_youtube_count_text_to_integer,
)

from .services.youtube_video_storage_service import (
    save_or_update_video_from_preview_data,
)

from .services.analysis_job_creation_service import (
    create_pending_analysis_job_for_video,
)

from .providers.selenium_youtube_provider import (
    get_video_comment_count,
)

"""測試影片與分析任務的資料庫規則。"""
class VideoAndAnalysisJobModelTests(TestCase):

    def setUp(self):
        """每個測試開始前建立一支測試影片。"""

        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="測試影片",
            video_author_name="測試頻道",
            video_thumbnail_url=(
                "https://"
                "i.ytimg.com/vi/"
                "dQw4w9WgXcQ/hqdefault.jpg"
            ),
            video_view_count=123_456,
            video_comment_count=789,
        )

    """新任務應使用 Selenium、等待處理及零進度。"""
    def test_analysis_job_uses_expected_defaults(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record)
        self.assertIsInstance(analysis_job.id, uuid.UUID)
        self.assertEqual(analysis_job.data_source,AnalysisJob.DataSource.SELENIUM)
        self.assertEqual(analysis_job.status,AnalysisJob.Status.PENDING)
        self.assertEqual(analysis_job.progress_percentage,0)
        self.assertEqual(analysis_job.error_message,"",)
        self.assertIsNone(analysis_job.started_at)
        self.assertIsNone(analysis_job.completed_at)

    """Video 應能透過 related_name 找到分析任務。"""
    def test_video_can_find_related_analysis_jobs(self):

        analysis_job = AnalysisJob.objects.create(video=self.video_record)

        related_analysis_job_exists = (
            self.video_record.analysis_jobs.filter(id=analysis_job.id).exists()
        )

        self.assertTrue(related_analysis_job_exists)
        self.assertEqual(analysis_job.video,self.video_record)

    """資料庫必須拒絕超過 100 的任務進度。"""
    def test_progress_percentage_cannot_exceed_100(self):

        with self.assertRaises(IntegrityError):
            # 使用獨立 Transaction，避免故意產生的資料庫錯誤
            # 破壞 Django TestCase 外層的測試 Transaction。
            with transaction.atomic():
                AnalysisJob.objects.create(video=self.video_record,progress_percentage=101)

    """已有分析任務的影片不可直接刪除。"""
    def test_video_with_analysis_job_is_protected_from_deletion(self):
        AnalysisJob.objects.create(video=self.video_record)
        with self.assertRaises(ProtectedError):
            self.video_record.delete()

    """相同 YouTube 影片 ID 不可建立兩筆 Video。"""
    def test_youtube_video_id_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Video.objects.create(youtube_video_id="dQw4w9WgXcQ",video_title="重複影片")


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

    """有效 YouTube 網址應取得並傳入影片預覽資料。"""
    @patch("analyses.views.get_video_preview_with_selenium")
    def test_new_analysis_form_accepts_supported_youtube_url(self,mock_get_video_preview_with_selenium):

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
        saved_video_record = response.context["saved_video_record"]

        self.assertIsNotNone(saved_video_record)
        self.assertEqual(Video.objects.count(), 1)
        self.assertEqual(saved_video_record.youtube_video_id,"dQw4w9WgXcQ")
        self.assertEqual(saved_video_record.video_title,"測試影片標題")
        self.assertEqual(saved_video_record.video_author_name,"測試頻道")
        self.assertEqual(saved_video_record.video_view_count,123_456)
        self.assertEqual(saved_video_record.video_comment_count,789)
        self.assertContains(response, "開始分析留言")
        self.assertContains(response, reverse("analyses:start_analysis", args=[saved_video_record.id]))

        mock_get_video_preview_with_selenium.assert_called_once_with(youtube_video_id="dQw4w9WgXcQ")


    """YouTube 回覆影片不可用時，應顯示錯誤卡片而不是 500。"""
    @patch("analyses.views.get_video_preview_with_selenium")
    def test_unavailable_youtube_video_renders_error_card(self,mock_get_video_preview_with_selenium):
        
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
        self.assertNotContains(response, "開始分析留言")

    """HTMX 驗證失敗時，只回傳表單區域及欄位錯誤。"""
    def test_htmx_invalid_url_returns_only_video_check_panel(self):

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


"""測試 Selenium 等待 YouTube 動態載入留言數。"""
class SeleniumYouTubeCommentCountTests(SimpleTestCase):
    @patch("analyses.providers.selenium_youtube_provider.sleep")
    def test_waits_until_comment_count_contains_number(self, mock_sleep):
        """只有「留言」時應繼續等待，直到取得完整數量。"""

        comment_label_element = MagicMock()
        comment_label_element.text = "留言"

        loaded_comment_count_element = MagicMock()
        loaded_comment_count_element.text = "2,313 則留言"

        chrome_driver = MagicMock()

        # 第一次只有「留言」，第二次才出現完整數字。
        chrome_driver.find_elements.side_effect = [
            [comment_label_element],
            [loaded_comment_count_element],
        ]

        actual_comment_count = get_video_comment_count(chrome_driver=chrome_driver)

        self.assertEqual(actual_comment_count, 2_313)
        self.assertEqual(chrome_driver.find_elements.call_count,2)
        mock_sleep.assert_called_once()


"""測試 YouTube 顯示數量的文字轉換。"""
class YouTubeCountParserTests(SimpleTestCase):

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

"""測試影片預覽資料寫入資料庫的邏輯。"""
class YouTubeVideoStorageServiceTests(TestCase):
    
    """第一次取得影片預覽時，應建立一筆 Video。"""
    def test_new_preview_data_creates_video_record(self):

        video_preview_data = YouTubeVideoPreviewData(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="第一次取得的影片標題",
            video_author_name="測試頻道",
            video_thumbnail_url=(
                "https://i.ytimg.com/vi/"
                "dQw4w9WgXcQ/hqdefault.jpg"
            ),
            video_view_count=123_456,
            video_comment_count=789,
        )

        saved_video_record = save_or_update_video_from_preview_data(video_preview_data=video_preview_data)

        self.assertEqual(Video.objects.count(), 1)
        self.assertEqual(saved_video_record.youtube_video_id,"dQw4w9WgXcQ")
        self.assertEqual(saved_video_record.video_title,"第一次取得的影片標題")
        self.assertEqual(saved_video_record.video_view_count,123_456)

    """再次取得同一支影片時，應更新原資料而不是新增第二筆。"""
    def test_existing_video_is_updated_instead_of_duplicated(self):
        
        existing_video_record = Video.objects.create(youtube_video_id="dQw4w9WgXcQ",video_title="舊的影片標題")

        updated_video_preview_data = YouTubeVideoPreviewData(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="更新後的影片標題",
            video_author_name="更新後的頻道",
            video_thumbnail_url=(
                "https://i.ytimg.com/vi/"
                "dQw4w9WgXcQ/maxresdefault.jpg"
            ),
            video_view_count=999_999,
            video_comment_count=1_234,
        )

        saved_video_record = save_or_update_video_from_preview_data(video_preview_data=updated_video_preview_data)
        existing_video_record.refresh_from_db()

        self.assertEqual(Video.objects.count(), 1)
        self.assertEqual(saved_video_record.id,existing_video_record.id)
        self.assertEqual(existing_video_record.video_title, "更新後的影片標題")
        self.assertEqual(existing_video_record.video_comment_count,1_234)


"""測試建立分析任務的 Service。"""
class AnalysisJobCreationServiceTests(TestCase):

    """每個測試開始前先建立一支影片。"""
    def setUp(self):
        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="準備分析的影片"
          )

    """開始分析時，應建立一個等待處理的任務。"""
    def test_creates_pending_analysis_job_for_video(self):

        created_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)

        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertEqual(created_analysis_job.video, self.video_record)
        self.assertEqual(created_analysis_job.data_source,AnalysisJob.DataSource.SELENIUM)
        self.assertEqual(created_analysis_job.status,AnalysisJob.Status.PENDING)
        self.assertEqual(created_analysis_job.progress_percentage,0)

    """同一支影片可以在不同時間建立多個分析任務。"""
    def test_each_analysis_request_creates_a_separate_job(self):

        first_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)
        second_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record) 

        self.assertEqual(AnalysisJob.objects.count(), 2)
        self.assertNotEqual(first_analysis_job.id, second_analysis_job.id)


"""測試從網站建立分析任務的流程。"""
class AnalysisJobStartViewTests(TestCase):

    def setUp(self):
        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="準備分析的影片",
        )

    def test_post_creates_job_and_redirects_to_job_page(self):
        """POST 開始分析後，應建立任務並導向任務頁。"""

        response = self.client.post(reverse("analyses:start_analysis", args=[self.video_record.id]))
        created_analysis_job = AnalysisJob.objects.get()

        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertEqual(created_analysis_job.video,self.video_record)
        self.assertRedirects(
            response,
            reverse("analyses:analysis_job_detail",args=[created_analysis_job.id]),
        )

    """GET 不可建立任務，必須回傳 405。"""
    def test_get_does_not_create_analysis_job(self):
        response = self.client.get(reverse("analyses:start_analysis",args=[self.video_record.id]))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(AnalysisJob.objects.count(), 0)


    """任務頁應顯示影片、狀態與進度。"""
    def test_analysis_job_detail_page_displays_job(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record)
        response = self.client.get(reverse("analyses:analysis_job_detail",args=[analysis_job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response,"analyses/analysis_job_detail.html")
        self.assertEqual(response.context["analysis_job"],analysis_job)
        self.assertContains(response, "準備分析的影片")
        self.assertContains(response, "等待處理")
        self.assertContains(response, "0%")