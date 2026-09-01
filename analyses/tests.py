import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase,TestCase #TestCase：每個測試之間隔離資料庫資料。
from django.urls import reverse #reverse()：透過 URL 名稱取得網址。
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from .forms import NewAnalysisForm
from .models import AnalysisJob, Comment, CommentObservation, FetchRun, Video
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

from .providers.youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)

from .providers.fake_youtube_provider import FakeYouTubeProvider
from .providers.selenium_youtube_provider import get_video_comment_count

from .services.youtube_fetch_service import (
    YouTubeCommentVideoMismatchError,
    fetch_and_store_youtube_comments,
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

    def setUp(self):
        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="準備分析的影片",
        )

    """建立任務時，應同時建立第一次抓取紀錄。"""
    def test_creates_pending_analysis_job_and_first_fetch_run(self):

        created_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)
        created_fetch_run = created_analysis_job.fetch_runs.get()

        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertEqual(FetchRun.objects.count(), 1)
        self.assertEqual(created_analysis_job.video, self.video_record)
        self.assertEqual(created_analysis_job.data_source, AnalysisJob.DataSource.SELENIUM)
        self.assertEqual(created_analysis_job.status, AnalysisJob.Status.PENDING)
        self.assertEqual(created_analysis_job.progress_percentage, 0)
        self.assertEqual(created_fetch_run.analysis_job, created_analysis_job)
        self.assertEqual(created_fetch_run.data_source, AnalysisJob.DataSource.SELENIUM)
        self.assertEqual(created_fetch_run.status, FetchRun.Status.PENDING)
        self.assertEqual(created_fetch_run.attempt_number, 1)
        self.assertEqual(created_fetch_run.fetched_comment_count, 0)

    """每次分析請求都應建立獨立任務與抓取紀錄。"""
    def test_each_analysis_request_creates_separate_job_and_fetch_run(self):

        first_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)
        second_analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)

        self.assertEqual(AnalysisJob.objects.count(), 2)
        self.assertEqual(FetchRun.objects.count(), 2)
        self.assertNotEqual(first_analysis_job.id, second_analysis_job.id)
        self.assertEqual(first_analysis_job.fetch_runs.get().attempt_number, 1)
        self.assertEqual(second_analysis_job.fetch_runs.get().attempt_number, 1)

    """FetchRun 建立失敗時，不可留下不完整的 AnalysisJob。"""
    @patch(
        "analyses.services.analysis_job_creation_service."
        "FetchRun.objects.create"
    )
    def test_analysis_job_is_rolled_back_when_fetch_run_creation_fails(self,mock_fetch_run_create):

        mock_fetch_run_create.side_effect = IntegrityError("模擬 FetchRun 建立失敗")
        with self.assertRaises(IntegrityError):
            create_pending_analysis_job_for_video(video_record=self.video_record)

        self.assertEqual(AnalysisJob.objects.count(), 0)
        self.assertEqual(FetchRun.objects.count(), 0)


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

"""測試留言抓取紀錄的資料庫規則。"""
class FetchRunModelTests(TestCase):

    def setUp(self):
        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="準備抓取留言的影片",
        )

        self.analysis_job = AnalysisJob.objects.create(video=self.video_record)
            
        

    """新抓取紀錄應為等待處理、第一次抓取及零留言。"""
    def test_fetch_run_uses_expected_defaults(self):

        fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
        )

        self.assertIsInstance(fetch_run.id, uuid.UUID)
        self.assertEqual(fetch_run.status, FetchRun.Status.PENDING)
        self.assertEqual(fetch_run.attempt_number, 1)
        self.assertEqual(fetch_run.fetched_comment_count, 0)
        self.assertEqual(fetch_run.error_code, "")
        self.assertEqual(fetch_run.error_message, "")

    def test_analysis_job_can_find_related_fetch_runs(self):
        """AnalysisJob 應能找到它的所有抓取紀錄。"""

        fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
        )

        self.assertTrue(self.analysis_job.fetch_runs.filter(id=fetch_run.id).exists())
        self.assertEqual(fetch_run.analysis_job, self.analysis_job)

    """同一任務不可建立兩筆相同抓取次數的紀錄。"""
    def test_same_job_cannot_have_duplicate_attempt_number(self):

        FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
            attempt_number=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FetchRun.objects.create(
                    analysis_job=self.analysis_job,
                    data_source=AnalysisJob.DataSource.SELENIUM,
                    attempt_number=1,
                )

    """抓取次數不可使用零。"""
    def test_attempt_number_must_start_from_one(self):

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FetchRun.objects.create(
                    analysis_job=self.analysis_job,
                    data_source=AnalysisJob.DataSource.SELENIUM,
                    attempt_number=0,
                )

    """刪除分析任務時，所屬抓取紀錄也應一起刪除。"""
    def test_deleting_analysis_job_also_deletes_fetch_runs(self):

        FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
        )

        self.analysis_job.delete()
        self.assertEqual(FetchRun.objects.count(), 0)


"""測試 YouTube 留言的資料庫規則。"""
class CommentModelTests(TestCase):

    def setUp(self):
        """每個測試開始前建立一支測試影片。"""

        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="留言測試影片",
        )

    def test_top_level_comment_can_be_created(self):
        """主留言應能建立並由 Video 反向查詢。"""

        comment_record = Comment.objects.create(
            youtube_comment_id="UgzTopLevelComment123",
            video=self.video_record,
            author_display_name="測試作者",
            comment_text="這是一則主留言。",
        )

        self.assertEqual(comment_record.video, self.video_record)
        self.assertIsNone(comment_record.parent_comment)
        self.assertIsNone(comment_record.like_count)
        self.assertFalse(comment_record.is_pinned)
        self.assertEqual(comment_record.parent_youtube_comment_id, "")
        self.assertTrue(self.video_record.comments.filter(id=comment_record.id).exists())

    """回覆留言應保存父留言關聯。"""
    def test_reply_comment_can_find_parent_comment(self):

        parent_comment = Comment.objects.create(
            youtube_comment_id="UgzParentComment123",
            video=self.video_record,
            author_display_name="主留言作者",
            comment_text="這是一則主留言。",
        )

        reply_comment = Comment.objects.create(
            youtube_comment_id="UgzReplyComment123",
            video=self.video_record,
            parent_youtube_comment_id=parent_comment.youtube_comment_id,
            parent_comment=parent_comment,
            author_display_name="回覆作者",
            comment_text="這是一則回覆。",
        )

        self.assertEqual(reply_comment.parent_comment, parent_comment)
        self.assertTrue(parent_comment.replies.filter(id=reply_comment.id).exists())
        self.assertEqual(reply_comment.parent_youtube_comment_id, parent_comment.youtube_comment_id)

    def test_youtube_comment_id_must_be_unique(self):
        """相同 YouTube 留言 ID 不可重複建立。"""

        Comment.objects.create(
            youtube_comment_id="UgzDuplicateComment123",
            video=self.video_record,
            comment_text="第一次抓到的留言。",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Comment.objects.create(
                    youtube_comment_id="UgzDuplicateComment123",
                    video=self.video_record,
                    comment_text="重複抓到的留言。",
                )

    def test_deleting_parent_comment_keeps_reply_comment(self):
        """刪除父留言後，回覆留言應保留但父留言關聯變成空值。"""

        parent_comment = Comment.objects.create(
            youtube_comment_id="UgzDeletedParent123",
            video=self.video_record,
            comment_text="之後會被刪除的父留言。",
        )

        reply_comment = Comment.objects.create(
            youtube_comment_id="UgzRemainingReply123",
            video=self.video_record,
            parent_comment=parent_comment,
            comment_text="父留言刪除後仍需保留的回覆。",
        )

        parent_comment.delete()
        reply_comment.refresh_from_db()

        self.assertIsNone(reply_comment.parent_comment)
        self.assertTrue(Comment.objects.filter(id=reply_comment.id).exists())

    def test_deleting_video_also_deletes_comments(self):
        """刪除影片時，所屬留言應一起刪除。"""

        Comment.objects.create(
            youtube_comment_id="UgzCascadeComment123",
            video=self.video_record,
            comment_text="影片刪除時一起刪除的留言。",
        )

        self.video_record.delete()

        self.assertEqual(Comment.objects.count(), 0)


"""測試留言觀察紀錄的資料庫規則。"""
class CommentObservationModelTests(TestCase):

    def setUp(self):
        """建立測試需要的影片、任務、抓取紀錄與留言。"""

        self.video_record = Video.objects.create(
            youtube_video_id="dQw4w9WgXcQ",
            video_title="留言觀察紀錄測試影片",
        )

        self.analysis_job = AnalysisJob.objects.create(
            video=self.video_record,
        )

        self.fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
        )

        self.comment_record = Comment.objects.create(
            youtube_comment_id="UgzObservedComment123",
            video=self.video_record,
            author_display_name="目前作者名稱",
            comment_text="目前留言內容",
            like_count=25,
        )

    def test_comment_observation_can_be_created(self):
        """抓取紀錄應能保存留言快照並反向查詢。"""

        comment_observation = CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_author_display_name="抓取時作者名稱",
            observed_comment_text="抓取時留言內容",
            observed_like_count=10,
            observed_published_time_text="2 天前",
            observed_is_pinned=True,
        )

        self.assertEqual(comment_observation.fetch_run, self.fetch_run)
        self.assertEqual(comment_observation.comment, self.comment_record)
        self.assertEqual(comment_observation.observed_like_count, 10)
        self.assertTrue(comment_observation.observed_is_pinned)
        self.assertIsNotNone(comment_observation.observed_at)
        self.assertTrue(self.fetch_run.comment_observations.filter(id=comment_observation.id).exists())
        self.assertTrue(self.comment_record.observations.filter(id=comment_observation.id).exists())

    def test_same_comment_cannot_be_observed_twice_in_same_fetch_run(self):
        """同一次抓取不可重複建立同一則留言的觀察紀錄。"""

        CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_comment_text="第一次觀察到的內容",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CommentObservation.objects.create(
                    fetch_run=self.fetch_run,
                    comment=self.comment_record,
                    observed_comment_text="同一次抓取的重複內容",
                )

    def test_same_comment_can_be_observed_in_different_fetch_runs(self):
        """不同抓取紀錄可以保存同一則留言的不同快照。"""

        second_fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
            attempt_number=2,
        )

        first_observation = CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_comment_text="第一次抓取的留言內容",
            observed_like_count=10,
        )

        second_observation = CommentObservation.objects.create(
            fetch_run=second_fetch_run,
            comment=self.comment_record,
            observed_comment_text="第二次抓取的留言內容",
            observed_like_count=25,
        )

        self.assertEqual(CommentObservation.objects.count(), 2)
        self.assertEqual(first_observation.observed_like_count, 10)
        self.assertEqual(second_observation.observed_like_count, 25)

    def test_updating_comment_does_not_change_existing_observation(self):
        """更新留言目前資料時，不可改變先前保存的抓取快照。"""

        comment_observation = CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_author_display_name="舊作者名稱",
            observed_comment_text="舊留言內容",
            observed_like_count=10,
        )

        self.comment_record.author_display_name = "新作者名稱"
        self.comment_record.comment_text = "新留言內容"
        self.comment_record.like_count = 25
        self.comment_record.save()
        comment_observation.refresh_from_db()

        self.assertEqual(comment_observation.observed_author_display_name, "舊作者名稱")
        self.assertEqual(comment_observation.observed_comment_text, "舊留言內容")
        self.assertEqual(comment_observation.observed_like_count, 10)

    def test_deleting_fetch_run_also_deletes_observations(self):
        """刪除抓取紀錄時，所屬觀察紀錄應一起刪除。"""

        CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_comment_text="準備一起刪除的快照",
        )

        self.fetch_run.delete()

        self.assertEqual(CommentObservation.objects.count(), 0)
        self.assertTrue(Comment.objects.filter(id=self.comment_record.id).exists())

    def test_deleting_comment_also_deletes_observations(self):
        """刪除留言時，所屬觀察紀錄應一起刪除。"""

        CommentObservation.objects.create(
            fetch_run=self.fetch_run,
            comment=self.comment_record,
            observed_comment_text="準備一起刪除的快照",
        )

        self.comment_record.delete()

        self.assertEqual(CommentObservation.objects.count(), 0)
        self.assertTrue(FetchRun.objects.filter(id=self.fetch_run.id).exists())


"""測試 YouTube Provider 使用的資料物件。"""
class YouTubeProviderDataTests(SimpleTestCase):

    def test_comment_data_uses_expected_values(self):
        """留言 DTO 應保存 Provider 取得的原始資料。"""

        comment_data = YouTubeCommentData(
            youtube_comment_id="UgzComment123",
            youtube_video_id="dQw4w9WgXcQ",
            comment_text="這是一則測試留言。",
            parent_youtube_comment_id="UgzParent123",
            author_display_name="測試作者",
            like_count=25,
            published_time_text="2 天前",
            is_pinned=True,
        )

        self.assertEqual(comment_data.youtube_comment_id, "UgzComment123")
        self.assertEqual(comment_data.parent_youtube_comment_id, "UgzParent123")
        self.assertEqual(comment_data.like_count, 25)
        self.assertTrue(comment_data.is_pinned)

    def test_fetch_options_use_expected_defaults(self):
        """抓取選項預設使用最新排序、包含回覆且不限數量。"""

        fetch_options = YouTubeCommentFetchOptions()

        self.assertEqual(fetch_options.sort_order, YouTubeCommentSortOrder.NEWEST)
        self.assertTrue(fetch_options.include_replies)
        self.assertIsNone(fetch_options.maximum_comment_count)

    def test_fetch_options_accept_comment_count_limit(self):
        """抓取選項應接受有效的留言數量上限。"""

        fetch_options = YouTubeCommentFetchOptions(maximum_comment_count=100)

        self.assertEqual(fetch_options.maximum_comment_count, 100)

    def test_fetch_options_reject_non_positive_comment_count_limit(self):
        """留言數量上限不可使用零或負數。"""

        with self.assertRaises(ValueError):
            YouTubeCommentFetchOptions(maximum_comment_count=0)


"""測試不連接外部網站的 Fake YouTube Provider。"""
class FakeYouTubeProviderTests(SimpleTestCase):

    def setUp(self):
        """建立固定影片及留言測試資料。"""

        self.youtube_video_id = "dQw4w9WgXcQ"
        base_published_at = datetime(2026, 9, 1, tzinfo=UTC)

        video_preview_data = YouTubeVideoPreviewData(
            youtube_video_id=self.youtube_video_id,
            video_title="Fake Provider 測試影片",
            video_author_name="測試頻道",
            video_thumbnail_url=None,
            video_view_count=1_000,
            video_comment_count=3,
        )

        self.parent_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzParent123",
            youtube_video_id=self.youtube_video_id,
            comment_text="較早發布但按讚數最多的主留言",
            like_count=100,
            published_at=base_published_at,
        )

        self.reply_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzReply123",
            youtube_video_id=self.youtube_video_id,
            parent_youtube_comment_id="UgzParent123",
            comment_text="回覆留言",
            like_count=20,
            published_at=base_published_at + timedelta(hours=1),
        )

        self.newest_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzNewest123",
            youtube_video_id=self.youtube_video_id,
            comment_text="最新發布的主留言",
            like_count=10,
            published_at=base_published_at + timedelta(hours=2),
        )

        self.fake_provider = FakeYouTubeProvider(
            video_preview_data=video_preview_data,
            comment_data=[
                self.parent_comment_data,
                self.reply_comment_data,
                self.newest_comment_data,
            ],
        )

    def test_get_video_preview_returns_configured_video(self):
        """Fake Provider 應回傳預先設定的影片資料。"""

        video_preview_data = self.fake_provider.get_video_preview(youtube_video_id=self.youtube_video_id)

        self.assertEqual(video_preview_data.youtube_video_id, self.youtube_video_id)
        self.assertEqual(video_preview_data.video_title, "Fake Provider 測試影片")

    def test_unknown_video_id_raises_unavailable_error(self):
        """查詢未設定的影片 ID 時應明確失敗。"""

        with self.assertRaises(YouTubeVideoUnavailableError):
            self.fake_provider.get_video_preview(youtube_video_id="unknown1234")

    def test_newest_sort_returns_comments_by_published_time(self):
        """最新排序應由新到舊回傳留言。"""

        comment_data = list(
            self.fake_provider.iter_video_comments(
                youtube_video_id=self.youtube_video_id,
                fetch_options=YouTubeCommentFetchOptions(),
            )
        )

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzNewest123", "UgzReply123", "UgzParent123"])

    def test_top_sort_returns_comments_by_like_count(self):
        """熱門排序應依按讚數由高到低回傳留言。"""

        comment_data = list(
            self.fake_provider.iter_video_comments(
                youtube_video_id=self.youtube_video_id,
                fetch_options=YouTubeCommentFetchOptions(sort_order=YouTubeCommentSortOrder.TOP),
            )
        )

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzParent123", "UgzReply123", "UgzNewest123"])

    def test_replies_can_be_excluded(self):
        """關閉回覆選項時，不應回傳具有父留言 ID 的留言。"""

        comment_data = list(
            self.fake_provider.iter_video_comments(
                youtube_video_id=self.youtube_video_id,
                fetch_options=YouTubeCommentFetchOptions(include_replies=False),
            )
        )

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzNewest123", "UgzParent123"])

    def test_comment_count_limit_is_applied(self):
        """留言數量上限應限制 Fake Provider 回傳的資料量。"""

        comment_data = list(
            self.fake_provider.iter_video_comments(
                youtube_video_id=self.youtube_video_id,
                fetch_options=YouTubeCommentFetchOptions(maximum_comment_count=2),
            )
        )

        self.assertEqual(len(comment_data), 2)


"""測試從 Provider 抓取並保存 YouTube 留言的 Service。"""
class YouTubeFetchServiceTests(TestCase):

    def setUp(self):
        """建立影片、任務、抓取紀錄與 Fake Provider。"""

        self.youtube_video_id = "dQw4w9WgXcQ"

        self.video_record = Video.objects.create(
            youtube_video_id=self.youtube_video_id,
            video_title="留言抓取 Service 測試影片",
        )

        self.analysis_job = AnalysisJob.objects.create(
            video=self.video_record,
        )

        self.fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
        )

        self.video_preview_data = YouTubeVideoPreviewData(
            youtube_video_id=self.youtube_video_id,
            video_title="留言抓取 Service 測試影片",
            video_author_name="測試頻道",
            video_thumbnail_url=None,
            video_view_count=1_000,
            video_comment_count=3,
        )

        base_published_at = datetime(2026, 9, 1, tzinfo=UTC)

        self.parent_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzParent123",
            youtube_video_id=self.youtube_video_id,
            comment_text="較早發布的父留言",
            author_display_name="父留言作者",
            like_count=100,
            published_at=base_published_at,
        )

        self.reply_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzReply123",
            youtube_video_id=self.youtube_video_id,
            parent_youtube_comment_id="UgzParent123",
            comment_text="父留言的回覆",
            author_display_name="回覆作者",
            like_count=20,
            published_at=base_published_at + timedelta(hours=1),
        )

        self.newest_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzNewest123",
            youtube_video_id=self.youtube_video_id,
            comment_text="最新留言",
            author_display_name="最新留言作者",
            like_count=10,
            published_at=base_published_at + timedelta(hours=2),
        )

        self.fake_provider = FakeYouTubeProvider(
            video_preview_data=self.video_preview_data,
            comment_data=[
                self.parent_comment_data,
                self.reply_comment_data,
                self.newest_comment_data,
            ],
        )

    def test_fetch_stores_comments_observations_and_parent_relationship(self):
        """Service 應保存留言、快照並補上父留言關聯。"""

        fetched_comment_count = fetch_and_store_youtube_comments(
            fetch_run=self.fetch_run,
            youtube_provider=self.fake_provider,
        )

        self.fetch_run.refresh_from_db()
        parent_comment = Comment.objects.get(youtube_comment_id="UgzParent123")
        reply_comment = Comment.objects.get(youtube_comment_id="UgzReply123")

        self.assertEqual(fetched_comment_count, 3)
        self.assertEqual(self.fetch_run.fetched_comment_count, 3)
        self.assertEqual(Comment.objects.count(), 3)
        self.assertEqual(CommentObservation.objects.count(), 3)
        self.assertEqual(reply_comment.parent_youtube_comment_id, "UgzParent123")
        self.assertEqual(reply_comment.parent_comment, parent_comment)

    def test_unresolved_parent_youtube_id_is_preserved(self):
        """只抓到回覆但尚未抓到父留言時，應保存原始父留言 ID。"""

        fetched_comment_count = fetch_and_store_youtube_comments(
            fetch_run=self.fetch_run,
            youtube_provider=self.fake_provider,
            fetch_options=YouTubeCommentFetchOptions(maximum_comment_count=2),
        )

        reply_comment = Comment.objects.get(youtube_comment_id="UgzReply123")

        self.assertEqual(fetched_comment_count, 2)
        self.assertEqual(reply_comment.parent_youtube_comment_id, "UgzParent123")
        self.assertIsNone(reply_comment.parent_comment)
        self.assertFalse(Comment.objects.filter(youtube_comment_id="UgzParent123").exists())

    def test_repeating_same_fetch_run_does_not_duplicate_records(self):
        """同一 FetchRun 重跑時，不可重複建立留言或觀察紀錄。"""

        fetch_and_store_youtube_comments(fetch_run=self.fetch_run, youtube_provider=self.fake_provider)
        fetch_and_store_youtube_comments(fetch_run=self.fetch_run, youtube_provider=self.fake_provider)

        self.fetch_run.refresh_from_db()

        self.assertEqual(Comment.objects.count(), 3)
        self.assertEqual(CommentObservation.objects.count(), 3)
        self.assertEqual(self.fetch_run.fetched_comment_count, 3)

    def test_new_fetch_run_updates_comment_and_keeps_old_observation(self):
        """新的抓取應更新留言目前資料，但保留舊快照。"""

        fetch_and_store_youtube_comments(fetch_run=self.fetch_run, youtube_provider=self.fake_provider)

        second_fetch_run = FetchRun.objects.create(
            analysis_job=self.analysis_job,
            data_source=AnalysisJob.DataSource.SELENIUM,
            attempt_number=2,
        )

        updated_comment_data = YouTubeCommentData(
            youtube_comment_id="UgzNewest123",
            youtube_video_id=self.youtube_video_id,
            comment_text="更新後的留言內容",
            author_display_name="最新留言作者",
            like_count=99,
            published_at=self.newest_comment_data.published_at,
        )

        updated_fake_provider = FakeYouTubeProvider(
            video_preview_data=self.video_preview_data,
            comment_data=[updated_comment_data],
        )

        fetch_and_store_youtube_comments(fetch_run=second_fetch_run, youtube_provider=updated_fake_provider)

        updated_comment = Comment.objects.get(youtube_comment_id="UgzNewest123")
        first_observation = CommentObservation.objects.get(fetch_run=self.fetch_run, comment=updated_comment)
        second_observation = CommentObservation.objects.get(fetch_run=second_fetch_run, comment=updated_comment)

        self.assertEqual(updated_comment.comment_text, "更新後的留言內容")
        self.assertEqual(updated_comment.like_count, 99)
        self.assertEqual(first_observation.observed_comment_text, "最新留言")
        self.assertEqual(first_observation.observed_like_count, 10)
        self.assertEqual(second_observation.observed_comment_text, "更新後的留言內容")
        self.assertEqual(second_observation.observed_like_count, 99)

    def test_provider_failure_keeps_successfully_stored_comments(self):
        """Provider 中途失敗時，已成功保存的留言與數量應保留。"""

        failing_provider = MagicMock(spec=YouTubeProvider)

        def failing_comment_iterator():
            yield self.newest_comment_data
            raise RuntimeError("模擬 Provider 中途失敗")

        failing_provider.iter_video_comments.return_value = failing_comment_iterator()

        with self.assertRaises(RuntimeError):
            fetch_and_store_youtube_comments(fetch_run=self.fetch_run, youtube_provider=failing_provider)

        self.fetch_run.refresh_from_db()

        self.assertEqual(Comment.objects.count(), 1)
        self.assertEqual(CommentObservation.objects.count(), 1)
        self.assertEqual(self.fetch_run.fetched_comment_count, 1)

    def test_existing_comment_from_another_video_is_rejected(self):
        """相同留言 ID 已屬於其他影片時，不可被移到目前影片。"""

        other_video_record = Video.objects.create(
            youtube_video_id="abcdefghijk",
            video_title="其他測試影片",
        )

        Comment.objects.create(
            youtube_comment_id="UgzNewest123",
            video=other_video_record,
            comment_text="其他影片的留言",
        )

        with self.assertRaises(YouTubeCommentVideoMismatchError):
            fetch_and_store_youtube_comments(fetch_run=self.fetch_run, youtube_provider=self.fake_provider)

        self.fetch_run.refresh_from_db()

        self.assertEqual(self.fetch_run.fetched_comment_count, 0)
        self.assertEqual(CommentObservation.objects.count(), 0)
        self.assertEqual(Comment.objects.get(youtube_comment_id="UgzNewest123").video, other_video_record)
