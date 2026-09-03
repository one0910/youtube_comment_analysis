import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase,TestCase #TestCase：每個測試之間隔離資料庫資料。
from django.urls import reverse #reverse()：透過 URL 名稱取得網址。
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from selenium.common.exceptions import TimeoutException

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
from .services.fetch_run_execution_service import (
    YouTubeProviderUnavailableError,
    execute_youtube_fetch_run,
    execute_youtube_fetch_run_by_id,
)
from .services.analysis_job_progress_service import (
    AnalysisStageState,
    build_analysis_stage_presentations,
)
from .tasks import execute_youtube_fetch_run_task

from .providers.youtube_provider import (
    YouTubeCommentData,
    YouTubeCommentFetchOptions,
    YouTubeCommentSortOrder,
    YouTubeProvider,
    YouTubeVideoPreviewData,
    YouTubeVideoUnavailableError,
)

from .providers.fake_youtube_provider import FakeYouTubeProvider
from .providers.selenium_youtube_provider import (
    VIDEO_COMMENT_THREAD_SELECTOR,
    InvalidYouTubeCommentElementError,
    SeleniumYouTubeProvider,
    expand_comment_replies,
    get_comment_like_count,
    get_loaded_top_level_comment_thread_elements,
    get_video_comment_count,
    get_video_like_count,
    get_youtube_comment_data_from_element,
    get_youtube_comment_id_from_url,
    iter_loaded_reply_comment_data,
    iter_loaded_top_level_comment_data,
    load_next_comment_batch,
    load_remaining_comment_replies,
    select_comment_sort_order,
)

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
            video_like_count=3_608,
        )

    """新任務應使用 Selenium、等待抓取留言且尚未開始執行。"""
    def test_analysis_job_uses_expected_defaults(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record)
        self.assertIsInstance(analysis_job.id, uuid.UUID)
        self.assertEqual(analysis_job.data_source,AnalysisJob.DataSource.SELENIUM)
        self.assertEqual(analysis_job.status,AnalysisJob.Status.PENDING)
        self.assertEqual(analysis_job.current_stage,AnalysisJob.Stage.COMMENT_FETCHING)
        self.assertEqual(analysis_job.get_current_stage_display(),"抓取留言")
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


"""測試分析任務資料轉換成五階段畫面狀態。"""
class AnalysisJobProgressServiceTests(SimpleTestCase):

    def test_pending_comment_fetch_displays_first_stage_completed_and_second_stage_current(self):
        analysis_job = AnalysisJob(status=AnalysisJob.Status.PENDING,current_stage=AnalysisJob.Stage.COMMENT_FETCHING)
        stage_presentations = build_analysis_stage_presentations(analysis_job=analysis_job)

        self.assertEqual([stage.state for stage in stage_presentations],[AnalysisStageState.COMPLETED, AnalysisStageState.CURRENT, AnalysisStageState.WAITING, AnalysisStageState.WAITING, AnalysisStageState.WAITING])
        self.assertEqual(stage_presentations[1].status_label,"準備中")

    def test_running_normalization_displays_third_stage_in_progress(self):
        analysis_job = AnalysisJob(status=AnalysisJob.Status.RUNNING,current_stage=AnalysisJob.Stage.COMMENT_NORMALIZATION)
        stage_presentations = build_analysis_stage_presentations(analysis_job=analysis_job)

        self.assertEqual([stage.state for stage in stage_presentations],[AnalysisStageState.COMPLETED, AnalysisStageState.COMPLETED, AnalysisStageState.CURRENT, AnalysisStageState.WAITING, AnalysisStageState.WAITING])
        self.assertEqual(stage_presentations[2].status_label,"進行中")

    def test_awaiting_ai_displays_ai_stage_as_current_and_waiting(self):
        analysis_job = AnalysisJob(status=AnalysisJob.Status.AWAITING_ANALYSIS,current_stage=AnalysisJob.Stage.AI_ANALYSIS)
        stage_presentations = build_analysis_stage_presentations(analysis_job=analysis_job)

        self.assertEqual([stage.state for stage in stage_presentations],[AnalysisStageState.COMPLETED, AnalysisStageState.COMPLETED, AnalysisStageState.COMPLETED, AnalysisStageState.CURRENT, AnalysisStageState.WAITING])
        self.assertEqual(stage_presentations[3].status_label,"等待中")

    def test_failed_job_marks_current_stage_as_failed_and_keeps_future_stages_waiting(self):
        analysis_job = AnalysisJob(status=AnalysisJob.Status.FAILED,current_stage=AnalysisJob.Stage.COMMENT_NORMALIZATION,error_message="模擬留言清理失敗")
        stage_presentations = build_analysis_stage_presentations(analysis_job=analysis_job)

        self.assertEqual([stage.state for stage in stage_presentations],[AnalysisStageState.COMPLETED, AnalysisStageState.COMPLETED, AnalysisStageState.FAILED, AnalysisStageState.WAITING, AnalysisStageState.WAITING])
        self.assertEqual(stage_presentations[2].status_label,"失敗")
        self.assertEqual(stage_presentations[2].description,"模擬留言清理失敗")


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
            video_like_count=3_608,
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
        self.assertEqual(saved_video_record.video_like_count,3_608)
        self.assertContains(response,"按讚數")
        self.assertContains(response,"3,608")
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


"""測試 Selenium 從 YouTube 原生影片資料取得按讚數。"""
class SeleniumYouTubeLikeCountTests(SimpleTestCase):

    def test_reads_exact_like_count_from_player_response(self):
        chrome_driver = MagicMock()
        chrome_driver.execute_script.return_value = "3608"

        actual_like_count = get_video_like_count(chrome_driver=chrome_driver)

        self.assertEqual(actual_like_count,3_608)

    def test_missing_like_count_returns_none(self):
        chrome_driver = MagicMock()
        chrome_driver.execute_script.return_value = None

        actual_like_count = get_video_like_count(chrome_driver=chrome_driver)

        self.assertIsNone(actual_like_count)


"""測試 Selenium 將單一 YouTube 留言元素轉成共用 DTO。"""
class SeleniumYouTubeCommentElementTests(SimpleTestCase):

    def test_comment_id_is_read_from_lc_query_parameter(self):
        """留言時間連結中的 lc 應作為穩定留言 ID。"""

        youtube_comment_id = get_youtube_comment_id_from_url(
            "/watch?v=dQw4w9WgXcQ&lc=UgzComment123"
        )

        self.assertEqual(youtube_comment_id, "UgzComment123")

    def test_comment_link_without_lc_parameter_is_rejected(self):
        """缺少 lc 的留言連結不可產生不可靠的留言 ID。"""

        with self.assertRaises(InvalidYouTubeCommentElementError):
            get_youtube_comment_id_from_url("/watch?v=dQw4w9WgXcQ")

    def test_empty_like_count_is_treated_as_zero(self):
        """YouTube 未顯示按讚文字時代表目前按讚數為零。"""

        self.assertEqual(get_comment_like_count(""), 0)

    def test_abbreviated_like_count_is_converted_to_integer(self):
        """中文縮寫的留言按讚數應轉成整數。"""

        self.assertEqual(get_comment_like_count("1.2萬"), 12_000)

    def test_comment_element_is_converted_to_expected_data(self):
        """已載入的留言元素應完整轉成 YouTubeCommentData。"""

        chrome_driver = MagicMock()
        comment_element = MagicMock()
        chrome_driver.execute_script.return_value = {
            "comment_link_url": "/watch?v=dQw4w9WgXcQ&lc=UgzReply123",
            "author_display_name": "@測試作者",
            "author_channel_url": "/@test-author",
            "comment_text": "這是一則回覆留言。",
            "like_count_text": "1.2萬",
            "published_time_text": "2 天前",
            "is_pinned": True,
        }

        comment_data = get_youtube_comment_data_from_element(
            chrome_driver=chrome_driver,
            comment_element=comment_element,
            youtube_video_id="dQw4w9WgXcQ",
            parent_youtube_comment_id="UgzParent123",
        )

        self.assertEqual(comment_data.youtube_comment_id, "UgzReply123")
        self.assertEqual(comment_data.youtube_video_id, "dQw4w9WgXcQ")
        self.assertEqual(comment_data.parent_youtube_comment_id, "UgzParent123")
        self.assertEqual(comment_data.author_display_name, "@測試作者")
        self.assertEqual(comment_data.author_channel_url, "https://www.youtube.com/@test-author")
        self.assertEqual(comment_data.comment_text, "這是一則回覆留言。")
        self.assertEqual(comment_data.like_count, 12_000)
        self.assertEqual(comment_data.published_time_text, "2 天前")
        self.assertTrue(comment_data.is_pinned)

    def test_non_dictionary_script_result_is_rejected(self):
        """YouTube DOM 結構失效時應回報明確錯誤。"""

        chrome_driver = MagicMock()
        chrome_driver.execute_script.return_value = None

        with self.assertRaises(InvalidYouTubeCommentElementError):
            get_youtube_comment_data_from_element(
                chrome_driver=chrome_driver,
                comment_element=MagicMock(),
                youtube_video_id="dQw4w9WgXcQ",
            )


"""測試 Selenium 逐筆轉換頁面中已載入的主留言。"""
class SeleniumYouTubeLoadedTopLevelCommentTests(SimpleTestCase):

    def test_top_level_thread_selector_excludes_reply_sub_threads(self):
        """回覆使用的 is-sub-thread 不可再次被當成主留言討論串。"""

        self.assertIn(":not([is-sub-thread])",VIDEO_COMMENT_THREAD_SELECTOR)

    def test_hidden_duplicate_comment_sections_are_ignored(self):
        """YouTube 頁面中的隱藏留言區不可加入主留言掃描清單。"""

        visible_comment_thread = MagicMock()
        hidden_comment_thread = MagicMock()
        visible_comment_thread.is_displayed.return_value = True
        hidden_comment_thread.is_displayed.return_value = False
        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [visible_comment_thread,hidden_comment_thread]

        comment_threads = get_loaded_top_level_comment_thread_elements(chrome_driver=chrome_driver)

        self.assertEqual(comment_threads,[visible_comment_thread])

    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_loaded_top_level_comments_are_yielded_in_dom_order(self, mock_get_comment_data):
        """已載入的主留言應依照 DOM 順序逐筆輸出。"""

        chrome_driver = MagicMock()
        first_comment_thread = MagicMock()
        second_comment_thread = MagicMock()
        chrome_driver.find_elements.return_value = [first_comment_thread, second_comment_thread]

        first_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123", youtube_video_id="dQw4w9WgXcQ", comment_text="第一則主留言")
        second_comment_data = YouTubeCommentData(youtube_comment_id="UgzSecond123", youtube_video_id="dQw4w9WgXcQ", comment_text="第二則主留言")
        mock_get_comment_data.side_effect = [first_comment_data, second_comment_data]

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ"))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzFirst123", "UgzSecond123"])
        self.assertEqual(first_comment_data.parent_youtube_comment_id, None)
        self.assertEqual(second_comment_data.parent_youtube_comment_id, None)
        self.assertEqual(mock_get_comment_data.call_count, 2)

    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_maximum_comment_count_stops_iteration_early(self, mock_get_comment_data):
        """達到留言數量上限後，不應繼續解析後面的 DOM 元素。"""

        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_get_comment_data.return_value = YouTubeCommentData(youtube_comment_id="UgzFirst123", youtube_video_id="dQw4w9WgXcQ", comment_text="第一則主留言")

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", maximum_comment_count=1))

        self.assertEqual(len(comment_data), 1)
        self.assertEqual(mock_get_comment_data.call_count, 1)

    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_iteration_can_start_after_previously_processed_threads(self, mock_get_comment_data):
        """下一批掃描應略過先前已處理的留言討論串。"""

        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_get_comment_data.return_value = YouTubeCommentData(youtube_comment_id="UgzThird123", youtube_video_id="dQw4w9WgXcQ", comment_text="第三則主留言")

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", start_comment_thread_index=2))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzThird123"])
        self.assertEqual(mock_get_comment_data.call_count, 1)

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_reply_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.load_remaining_comment_replies")
    @patch("analyses.providers.selenium_youtube_provider.expand_comment_replies", return_value=True)
    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_loaded_replies_are_yielded_after_top_level_comment(self, mock_get_comment_data, mock_expand_replies, mock_load_remaining_replies, mock_iter_replies):
        """啟用回覆時，應先輸出主留言，再輸出它的回覆。"""

        chrome_driver = MagicMock()
        comment_thread_element = MagicMock()
        chrome_driver.find_elements.return_value = [comment_thread_element]
        top_level_comment_data = YouTubeCommentData(youtube_comment_id="UgzParent123", youtube_video_id="dQw4w9WgXcQ", comment_text="主留言")
        reply_comment_data = YouTubeCommentData(youtube_comment_id="UgzReply123", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="回覆留言")
        mock_get_comment_data.return_value = top_level_comment_data
        mock_iter_replies.return_value = iter([reply_comment_data])

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", include_replies=True))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzParent123", "UgzReply123"])
        mock_expand_replies.assert_called_once_with(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element)
        mock_load_remaining_replies.assert_called_once_with(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element, maximum_reply_count=None)
        mock_iter_replies.assert_called_once_with(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element, youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", maximum_reply_count=None)

    @patch("analyses.providers.selenium_youtube_provider.expand_comment_replies")
    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_replies_are_not_expanded_when_disabled(self, mock_get_comment_data, mock_expand_replies):
        """關閉回覆選項時，不應點擊任何回覆按鈕。"""

        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [MagicMock()]
        mock_get_comment_data.return_value = YouTubeCommentData(youtube_comment_id="UgzParent123", youtube_video_id="dQw4w9WgXcQ", comment_text="主留言")

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", include_replies=False))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzParent123"])
        mock_expand_replies.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_reply_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.load_remaining_comment_replies")
    @patch("analyses.providers.selenium_youtube_provider.expand_comment_replies", return_value=True)
    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_maximum_comment_count_includes_replies(self, mock_get_comment_data, mock_expand_replies, mock_load_remaining_replies, mock_iter_replies):
        """留言數量上限應同時計算主留言與回覆。"""

        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [MagicMock(), MagicMock()]
        top_level_comment_data = YouTubeCommentData(youtube_comment_id="UgzParent123", youtube_video_id="dQw4w9WgXcQ", comment_text="主留言")
        first_reply_data = YouTubeCommentData(youtube_comment_id="UgzReplyOne", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="第一則回覆")
        second_reply_data = YouTubeCommentData(youtube_comment_id="UgzReplyTwo", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="第二則回覆")
        mock_get_comment_data.return_value = top_level_comment_data
        mock_iter_replies.return_value = iter([first_reply_data, second_reply_data])

        comment_data = list(iter_loaded_top_level_comment_data(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", maximum_comment_count=2, include_replies=True))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzParent123", "UgzReplyOne"])
        mock_load_remaining_replies.assert_called_once_with(chrome_driver=chrome_driver, comment_thread_element=chrome_driver.find_elements.return_value[0], maximum_reply_count=1)
        mock_iter_replies.assert_called_once_with(chrome_driver=chrome_driver, comment_thread_element=chrome_driver.find_elements.return_value[0], youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", maximum_reply_count=1)


"""測試 Selenium Provider 的主留言抓取入口。"""
class SeleniumYouTubeCommentIteratorTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.select_comment_sort_order")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count",return_value=2)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_never_yields_the_same_comment_id_twice(self,mock_create_driver,mock_check_video,mock_get_comment_count,mock_select_sort,mock_iter_comments):
        """DOM 重複或重新渲染時，相同留言 ID 只能輸出一次。"""

        chrome_driver = mock_create_driver.return_value
        chrome_driver.find_elements.return_value = [MagicMock()]
        first_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123",youtube_video_id="dQw4w9WgXcQ",comment_text="第一則留言")
        duplicated_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123",youtube_video_id="dQw4w9WgXcQ",comment_text="第一則留言")
        second_comment_data = YouTubeCommentData(youtube_comment_id="UgzSecond123",youtube_video_id="dQw4w9WgXcQ",comment_text="第二則留言")
        mock_iter_comments.return_value = iter([first_comment_data,duplicated_comment_data,second_comment_data])

        comment_data = list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ",fetch_options=YouTubeCommentFetchOptions(maximum_comment_count=2)))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data],["UgzFirst123","UgzSecond123"])
        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.select_comment_sort_order")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count", return_value=2)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_opens_video_and_yields_loaded_comments(self, mock_create_driver, mock_check_video, mock_get_comment_count, mock_select_sort, mock_iter_comments):
        """Provider 應開啟指定影片並逐筆輸出已載入留言。"""

        chrome_driver = mock_create_driver.return_value
        first_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123", youtube_video_id="dQw4w9WgXcQ", comment_text="第一則主留言")
        second_comment_data = YouTubeCommentData(youtube_comment_id="UgzSecond123", youtube_video_id="dQw4w9WgXcQ", comment_text="第二則主留言")
        mock_iter_comments.return_value = iter([first_comment_data, second_comment_data])

        comment_data = list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions(maximum_comment_count=2)))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzFirst123", "UgzSecond123"])
        chrome_driver.get.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        mock_check_video.assert_called_once()
        mock_get_comment_count.assert_called_once_with(chrome_driver=chrome_driver)
        mock_select_sort.assert_called_once_with(chrome_driver=chrome_driver, sort_order=YouTubeCommentSortOrder.NEWEST)
        mock_iter_comments.assert_called_once_with(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", maximum_comment_count=2, start_comment_thread_index=0, include_replies=True)
        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.select_comment_sort_order")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count", return_value=1)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_passes_disabled_reply_option_to_iterator(self, mock_create_driver, mock_check_video, mock_get_comment_count, mock_select_sort, mock_iter_comments):
        """關閉回覆選項時，Provider 應將設定傳入已載入留言迭代器。"""

        chrome_driver = mock_create_driver.return_value
        comment_data = YouTubeCommentData(youtube_comment_id="UgzParent123", youtube_video_id="dQw4w9WgXcQ", comment_text="主留言")
        mock_iter_comments.return_value = iter([comment_data])

        list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions(include_replies=False, maximum_comment_count=1)))

        mock_iter_comments.assert_called_once_with(chrome_driver=chrome_driver, youtube_video_id="dQw4w9WgXcQ", maximum_comment_count=1, start_comment_thread_index=0, include_replies=False)
        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count", return_value=None)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_video_without_comment_count_returns_no_comments(self, mock_create_driver, mock_check_video, mock_get_comment_count, mock_iter_comments):
        """留言關閉或沒有留言時，Provider 應回傳空結果並關閉 Chrome。"""

        chrome_driver = mock_create_driver.return_value

        comment_data = list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions()))

        self.assertEqual(comment_data, [])
        mock_iter_comments.assert_not_called()
        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available", side_effect=RuntimeError("模擬影片檢查失敗"))
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_failure_still_closes_chrome(self, mock_create_driver, mock_check_video):
        """影片檢查失敗時仍必須關閉 Chrome。"""

        chrome_driver = mock_create_driver.return_value

        with self.assertRaises(RuntimeError):
            list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions()))

        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.load_next_comment_batch", return_value=True)
    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.select_comment_sort_order")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count", return_value=3)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_yields_comments_from_multiple_batches(self, mock_create_driver, mock_check_video, mock_get_comment_count, mock_select_sort, mock_iter_comments, mock_load_next_batch):
        """Provider 應持續載入批次，直到取得顯示的留言總數。"""

        chrome_driver = mock_create_driver.return_value
        chrome_driver.find_elements.side_effect = [[MagicMock()], [MagicMock(), MagicMock(), MagicMock()]]
        first_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123", youtube_video_id="dQw4w9WgXcQ", comment_text="第一批留言")
        second_comment_data = YouTubeCommentData(youtube_comment_id="UgzSecond123", youtube_video_id="dQw4w9WgXcQ", comment_text="第二批留言")
        third_comment_data = YouTubeCommentData(youtube_comment_id="UgzThird123", youtube_video_id="dQw4w9WgXcQ", comment_text="第二批留言")
        mock_iter_comments.side_effect = [iter([first_comment_data]), iter([second_comment_data, third_comment_data])]

        comment_data = list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions()))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzFirst123", "UgzSecond123", "UgzThird123"])
        self.assertEqual(mock_iter_comments.call_count, 2)
        mock_load_next_batch.assert_called_once_with(chrome_driver=chrome_driver, previous_comment_thread_count=1)
        chrome_driver.quit.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.load_next_comment_batch", return_value=False)
    @patch("analyses.providers.selenium_youtube_provider.iter_loaded_top_level_comment_data")
    @patch("analyses.providers.selenium_youtube_provider.select_comment_sort_order")
    @patch("analyses.providers.selenium_youtube_provider.get_video_comment_count", return_value=100)
    @patch("analyses.providers.selenium_youtube_provider.check_youtube_video_is_available")
    @patch("analyses.providers.selenium_youtube_provider.create_local_chrome_driver")
    def test_provider_stops_after_repeated_batch_timeouts(self, mock_create_driver, mock_check_video, mock_get_comment_count, mock_select_sort, mock_iter_comments, mock_load_next_batch):
        """連續多次沒有新留言時應停止，避免無限捲動。"""

        chrome_driver = mock_create_driver.return_value
        chrome_driver.find_elements.return_value = [MagicMock()]
        first_comment_data = YouTubeCommentData(youtube_comment_id="UgzFirst123", youtube_video_id="dQw4w9WgXcQ", comment_text="唯一成功載入的留言")
        mock_iter_comments.side_effect = [iter([first_comment_data]), iter([]), iter([])]

        comment_data = list(SeleniumYouTubeProvider().iter_video_comments(youtube_video_id="dQw4w9WgXcQ", fetch_options=YouTubeCommentFetchOptions()))

        self.assertEqual([comment.youtube_comment_id for comment in comment_data], ["UgzFirst123"])
        self.assertEqual(mock_load_next_batch.call_count, 3)
        chrome_driver.quit.assert_called_once()


"""測試 Selenium 捲動頁面並等待下一批留言。"""
class SeleniumYouTubeCommentBatchLoadingTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_new_comment_batch_returns_true(self, mock_web_driver_wait):
        """應捲到留言 continuation，並在留言數量增加時回傳 True。"""

        chrome_driver = MagicMock()
        visible_continuation = MagicMock()
        visible_continuation.is_displayed.return_value = True
        chrome_driver.find_elements.return_value = [visible_continuation]
        mock_web_driver_wait.return_value.until.return_value = True

        new_comment_batch_loaded = load_next_comment_batch(chrome_driver=chrome_driver, previous_comment_thread_count=20)

        self.assertTrue(new_comment_batch_loaded)
        chrome_driver.execute_script.assert_called_once_with("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",visible_continuation)
        mock_web_driver_wait.return_value.until.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_comment_batch_timeout_returns_false(self, mock_web_driver_wait):
        """捲動後沒有增加留言時應回傳 False。"""

        chrome_driver = MagicMock()
        visible_continuation = MagicMock()
        visible_continuation.is_displayed.return_value = True
        chrome_driver.find_elements.return_value = [visible_continuation]
        mock_web_driver_wait.return_value.until.side_effect = TimeoutException("模擬等待新留言逾時")

        new_comment_batch_loaded = load_next_comment_batch(chrome_driver=chrome_driver, previous_comment_thread_count=20)

        self.assertFalse(new_comment_batch_loaded)

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_missing_visible_comment_continuation_finishes_loading(self,mock_web_driver_wait):
        """沒有可見的留言 continuation 時，代表已無下一批留言。"""

        hidden_continuation = MagicMock()
        hidden_continuation.is_displayed.return_value = False
        chrome_driver = MagicMock()
        chrome_driver.find_elements.return_value = [hidden_continuation]

        new_comment_batch_loaded = load_next_comment_batch(chrome_driver=chrome_driver,previous_comment_thread_count=20)

        self.assertFalse(new_comment_batch_loaded)
        chrome_driver.execute_script.assert_not_called()
        mock_web_driver_wait.assert_not_called()


"""測試 Selenium 展開一則主留言的回覆區。"""
class SeleniumYouTubeCommentReplyExpansionTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_visible_reply_button_is_clicked(self, mock_web_driver_wait):
        """主留言有回覆時應點擊可見的展開按鈕並等待回覆元素。"""

        chrome_driver = MagicMock()
        comment_thread_element = MagicMock()
        hidden_reply_button = MagicMock()
        visible_reply_button = MagicMock()
        hidden_reply_button.is_displayed.return_value = False
        visible_reply_button.is_displayed.return_value = True
        comment_thread_element.find_elements.return_value = [hidden_reply_button, visible_reply_button]
        mock_web_driver_wait.return_value.until.return_value = True

        replies_expanded = expand_comment_replies(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element)

        self.assertTrue(replies_expanded)
        visible_reply_button.click.assert_called_once()
        hidden_reply_button.click.assert_not_called()
        chrome_driver.execute_script.assert_called_once()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_comment_without_reply_button_returns_false(self, mock_web_driver_wait):
        """沒有可見回覆按鈕時代表主留言目前沒有回覆。"""

        comment_thread_element = MagicMock()
        comment_thread_element.find_elements.return_value = []

        replies_expanded = expand_comment_replies(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element)

        self.assertFalse(replies_expanded)
        mock_web_driver_wait.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_reply_loading_timeout_is_not_hidden(self, mock_web_driver_wait):
        """按鈕存在但回覆載入失敗時應保留逾時錯誤。"""

        comment_thread_element = MagicMock()
        visible_reply_button = MagicMock()
        visible_reply_button.is_displayed.return_value = True
        comment_thread_element.find_elements.return_value = [visible_reply_button]
        mock_web_driver_wait.return_value.until.side_effect = TimeoutException("模擬回覆載入逾時")

        with self.assertRaises(TimeoutException):
            expand_comment_replies(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element)


"""測試 Selenium 持續載入同一則主留言的後續回覆。"""
class SeleniumYouTubeReplyContinuationTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_visible_continuation_buttons_are_clicked_until_they_disappear(self, mock_web_driver_wait):
        """有多批回覆時，應反覆點擊顯示更多回覆直到按鈕消失。"""

        chrome_driver = MagicMock()
        comment_thread_element = MagicMock()
        first_continuation_button = MagicMock()
        second_continuation_button = MagicMock()
        first_continuation_button.is_displayed.return_value = True
        second_continuation_button.is_displayed.return_value = True
        comment_thread_element.find_elements.side_effect = [[MagicMock()], [first_continuation_button], [MagicMock(), MagicMock()], [second_continuation_button], [MagicMock(), MagicMock(), MagicMock()], []]
        mock_web_driver_wait.return_value.until.return_value = True

        load_remaining_comment_replies(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element)

        first_continuation_button.click.assert_called_once()
        second_continuation_button.click.assert_called_once()
        self.assertEqual(mock_web_driver_wait.return_value.until.call_count, 2)

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_missing_visible_continuation_button_finishes_loading(self, mock_web_driver_wait):
        """沒有可見的顯示更多回覆按鈕時，代表目前回覆已全部載入。"""

        hidden_continuation_button = MagicMock()
        hidden_continuation_button.is_displayed.return_value = False
        comment_thread_element = MagicMock()
        comment_thread_element.find_elements.side_effect = [[MagicMock()], [hidden_continuation_button]]

        load_remaining_comment_replies(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element)

        hidden_continuation_button.click.assert_not_called()
        mock_web_driver_wait.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_reply_limit_avoids_unnecessary_continuation_click(self, mock_web_driver_wait):
        """已載入足夠回覆時，不應繼續點擊顯示更多回覆。"""

        comment_thread_element = MagicMock()
        comment_thread_element.find_elements.return_value = [MagicMock(), MagicMock()]

        load_remaining_comment_replies(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element, maximum_reply_count=2)

        self.assertEqual(comment_thread_element.find_elements.call_count, 1)
        mock_web_driver_wait.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_continuation_loading_timeout_is_not_hidden(self, mock_web_driver_wait):
        """更多回覆載入失敗時，應保留逾時錯誤供上層處理。"""

        visible_continuation_button = MagicMock()
        visible_continuation_button.is_displayed.return_value = True
        comment_thread_element = MagicMock()
        comment_thread_element.find_elements.side_effect = [[MagicMock()], [visible_continuation_button]]
        mock_web_driver_wait.return_value.until.side_effect = TimeoutException("模擬更多回覆載入逾時")

        with self.assertRaises(TimeoutException):
            load_remaining_comment_replies(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element)


"""測試 Selenium 逐筆轉換已載入的回覆留言。"""
class SeleniumYouTubeLoadedReplyCommentTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_loaded_replies_use_top_level_comment_as_parent(self, mock_get_comment_data):
        """回覆 DTO 應保存所屬主留言的 YouTube 留言 ID。"""

        chrome_driver = MagicMock()
        comment_thread_element = MagicMock()
        first_reply_element = MagicMock()
        second_reply_element = MagicMock()
        comment_thread_element.find_elements.return_value = [first_reply_element, second_reply_element]
        first_reply_data = YouTubeCommentData(youtube_comment_id="UgzReplyOne", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="第一則回覆")
        second_reply_data = YouTubeCommentData(youtube_comment_id="UgzReplyTwo", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="第二則回覆")
        mock_get_comment_data.side_effect = [first_reply_data, second_reply_data]

        reply_data = list(iter_loaded_reply_comment_data(chrome_driver=chrome_driver, comment_thread_element=comment_thread_element, youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123"))

        self.assertEqual([reply.youtube_comment_id for reply in reply_data], ["UgzReplyOne", "UgzReplyTwo"])
        self.assertTrue(all(reply.parent_youtube_comment_id == "UgzParent123" for reply in reply_data))
        mock_get_comment_data.assert_any_call(chrome_driver=chrome_driver, comment_element=first_reply_element, youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123")

    @patch("analyses.providers.selenium_youtube_provider.get_youtube_comment_data_from_element")
    def test_reply_count_limit_stops_iteration_early(self, mock_get_comment_data):
        """達到剩餘數量上限後，不應繼續解析後面的回覆元素。"""

        comment_thread_element = MagicMock()
        comment_thread_element.find_elements.return_value = [MagicMock(), MagicMock()]
        mock_get_comment_data.return_value = YouTubeCommentData(youtube_comment_id="UgzReplyOne", youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", comment_text="第一則回覆")

        reply_data = list(iter_loaded_reply_comment_data(chrome_driver=MagicMock(), comment_thread_element=comment_thread_element, youtube_video_id="dQw4w9WgXcQ", parent_youtube_comment_id="UgzParent123", maximum_reply_count=1))

        self.assertEqual(len(reply_data), 1)
        self.assertEqual(mock_get_comment_data.call_count, 1)


"""測試 Selenium 切換 YouTube 留言排序。"""
class SeleniumYouTubeCommentSortTests(SimpleTestCase):

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_newest_sort_clicks_second_option(self, mock_web_driver_wait):
        """最新排序應選擇排序選單中的第二個選項。"""

        sort_button = MagicMock()
        top_option = MagicMock()
        newest_option = MagicMock()
        top_option.get_attribute.return_value = "true"
        newest_option.get_attribute.return_value = "false"
        mock_web_driver_wait.return_value.until.side_effect = [sort_button, [top_option, newest_option], True, True]

        select_comment_sort_order(chrome_driver=MagicMock(), sort_order=YouTubeCommentSortOrder.NEWEST)

        sort_button.click.assert_called_once()
        newest_option.click.assert_called_once()
        top_option.click.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_selected_top_sort_only_closes_menu(self, mock_web_driver_wait):
        """已經選取熱門排序時，只需要關閉剛開啟的選單。"""

        sort_button = MagicMock()
        top_option = MagicMock()
        newest_option = MagicMock()
        top_option.get_attribute.return_value = "true"
        newest_option.get_attribute.return_value = "false"
        mock_web_driver_wait.return_value.until.side_effect = [sort_button, [top_option, newest_option]]

        select_comment_sort_order(chrome_driver=MagicMock(), sort_order=YouTubeCommentSortOrder.TOP)

        self.assertEqual(sort_button.click.call_count, 2)
        top_option.click.assert_not_called()
        newest_option.click.assert_not_called()

    @patch("analyses.providers.selenium_youtube_provider.WebDriverWait")
    def test_missing_sort_option_raises_timeout(self, mock_web_driver_wait):
        """排序選單缺少預期選項時應回報版面結構錯誤。"""

        mock_web_driver_wait.return_value.until.side_effect = [MagicMock(), [MagicMock()]]

        with self.assertRaises(TimeoutException):
            select_comment_sort_order(chrome_driver=MagicMock(), sort_order=YouTubeCommentSortOrder.NEWEST)

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
            video_like_count=3_608,
        )

        saved_video_record = save_or_update_video_from_preview_data(video_preview_data=video_preview_data)

        self.assertEqual(Video.objects.count(), 1)
        self.assertEqual(saved_video_record.youtube_video_id,"dQw4w9WgXcQ")
        self.assertEqual(saved_video_record.video_title,"第一次取得的影片標題")
        self.assertEqual(saved_video_record.video_view_count,123_456)
        self.assertEqual(saved_video_record.video_like_count,3_608)

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
            video_like_count=9_876,
        )

        saved_video_record = save_or_update_video_from_preview_data(video_preview_data=updated_video_preview_data)
        existing_video_record.refresh_from_db()

        self.assertEqual(Video.objects.count(), 1)
        self.assertEqual(saved_video_record.id,existing_video_record.id)
        self.assertEqual(existing_video_record.video_title, "更新後的影片標題")
        self.assertEqual(existing_video_record.video_comment_count,1_234)
        self.assertEqual(existing_video_record.video_like_count,9_876)


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


"""測試留言抓取執行期間的任務狀態生命週期。"""
class FetchRunExecutionServiceTests(TestCase):

    def setUp(self):
        self.video_record = Video.objects.create(youtube_video_id="dQw4w9WgXcQ", video_title="準備執行抓取的影片")
        self.analysis_job = create_pending_analysis_job_for_video(video_record=self.video_record)
        self.fetch_run = self.analysis_job.fetch_runs.get(attempt_number=1)
        self.youtube_provider = MagicMock(spec=YouTubeProvider)
        self.fetch_options = YouTubeCommentFetchOptions(maximum_comment_count=3)

    @patch("analyses.services.fetch_run_execution_service.fetch_and_store_youtube_comments", return_value=3)
    def test_successful_fetch_updates_job_and_fetch_run_statuses(self, mock_fetch_and_store):
        """抓取成功後，FetchRun 應完成且 AnalysisJob 應等待 AI 分析。"""

        stored_comment_count = execute_youtube_fetch_run(fetch_run=self.fetch_run, youtube_provider=self.youtube_provider, fetch_options=self.fetch_options)
        self.fetch_run.refresh_from_db()
        self.analysis_job.refresh_from_db()

        self.assertEqual(stored_comment_count, 3)
        self.assertEqual(self.fetch_run.status, FetchRun.Status.COMPLETED)
        self.assertEqual(self.fetch_run.fetched_comment_count, 3)
        self.assertIsNotNone(self.fetch_run.started_at)
        self.assertIsNotNone(self.fetch_run.completed_at)
        self.assertEqual(self.fetch_run.error_code, "")
        self.assertEqual(self.fetch_run.error_message, "")
        self.assertEqual(self.analysis_job.status, AnalysisJob.Status.AWAITING_ANALYSIS)
        self.assertEqual(self.analysis_job.current_stage, AnalysisJob.Stage.AI_ANALYSIS)
        self.assertIsNotNone(self.analysis_job.started_at)
        self.assertIsNone(self.analysis_job.completed_at)
        self.assertEqual(self.analysis_job.error_message, "")
        mock_fetch_and_store.assert_called_once_with(fetch_run=self.fetch_run, youtube_provider=self.youtube_provider, fetch_options=self.fetch_options)

    @patch("analyses.services.fetch_run_execution_service.fetch_and_store_youtube_comments", side_effect=RuntimeError("模擬 Selenium 抓取失敗"))
    def test_failed_fetch_saves_error_and_reraises_exception(self, mock_fetch_and_store):
        """抓取失敗時，任務與抓取紀錄都應保存錯誤並重新拋出例外。"""

        with self.assertRaisesRegex(RuntimeError, "模擬 Selenium 抓取失敗"):
            execute_youtube_fetch_run(fetch_run=self.fetch_run, youtube_provider=self.youtube_provider, fetch_options=self.fetch_options)

        self.fetch_run.refresh_from_db()
        self.analysis_job.refresh_from_db()
        self.assertEqual(self.fetch_run.status, FetchRun.Status.FAILED)
        self.assertEqual(self.fetch_run.error_code, "RuntimeError")
        self.assertEqual(self.fetch_run.error_message, "模擬 Selenium 抓取失敗")
        self.assertIsNotNone(self.fetch_run.started_at)
        self.assertIsNotNone(self.fetch_run.completed_at)
        self.assertEqual(self.analysis_job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(self.analysis_job.current_stage, AnalysisJob.Stage.COMMENT_FETCHING)
        self.assertEqual(self.analysis_job.error_message, "模擬 Selenium 抓取失敗")
        self.assertIsNotNone(self.analysis_job.started_at)
        self.assertIsNotNone(self.analysis_job.completed_at)

    @patch("analyses.services.fetch_run_execution_service.execute_youtube_fetch_run", return_value=3)
    @patch("analyses.services.fetch_run_execution_service.SeleniumYouTubeProvider")
    def test_fetch_run_id_selects_selenium_provider_and_executes_fetch(self, mock_selenium_provider_class, mock_execute_fetch_run):
        """入口應由 FetchRun ID 載入資料並建立 Selenium Provider。"""

        stored_comment_count = execute_youtube_fetch_run_by_id(fetch_run_id=str(self.fetch_run.id), fetch_options=self.fetch_options)

        self.assertEqual(stored_comment_count, 3)
        mock_selenium_provider_class.assert_called_once_with()
        mock_execute_fetch_run.assert_called_once_with(fetch_run=self.fetch_run, youtube_provider=mock_selenium_provider_class.return_value, fetch_options=self.fetch_options)

    @patch("analyses.services.fetch_run_execution_service.SeleniumYouTubeProvider")
    def test_youtube_api_fetch_run_reports_provider_is_unavailable(self, mock_selenium_provider_class):
        """YouTube API Provider 尚未完成時，應回報明確錯誤。"""

        self.fetch_run.data_source = AnalysisJob.DataSource.YOUTUBE_API
        self.fetch_run.save(update_fields=["data_source", "updated_at"])

        with self.assertRaisesRegex(YouTubeProviderUnavailableError, "尚未實作"):
            execute_youtube_fetch_run_by_id(fetch_run_id=self.fetch_run.id)

        mock_selenium_provider_class.assert_not_called()

    def test_unknown_data_source_is_rejected(self):
        """資料來源值不受支援時，不可靜默改用其他 Provider。"""

        self.fetch_run.data_source = "unknown_source"
        self.fetch_run.save(update_fields=["data_source", "updated_at"])

        with self.assertRaisesRegex(YouTubeProviderUnavailableError, "unknown_source"):
            execute_youtube_fetch_run_by_id(fetch_run_id=self.fetch_run.id)


"""測試 Celery 留言抓取任務的邊界。"""
class YouTubeFetchTaskTests(SimpleTestCase):

    def test_task_uses_expected_name_and_queue(self):
        """Selenium 抓取任務應固定送往專用 Queue。"""

        self.assertEqual(execute_youtube_fetch_run_task.name,"analyses.execute_youtube_fetch_run")
        self.assertEqual(execute_youtube_fetch_run_task.queue,"youtube_selenium")
        self.assertTrue(execute_youtube_fetch_run_task.ignore_result)

    @patch("analyses.tasks.execute_youtube_fetch_run_by_id",return_value=12)
    def test_task_executes_fetch_run_by_id(self,mock_execute_fetch_run):
        """Task 只傳遞 FetchRun ID，實際流程交由既有 Service 執行。"""

        fetch_run_id = str(uuid.uuid4())
        stored_comment_count = execute_youtube_fetch_run_task.run(fetch_run_id=fetch_run_id,maximum_comment_count=5)

        self.assertEqual(stored_comment_count,12)
        mock_execute_fetch_run.assert_called_once()
        self.assertEqual(mock_execute_fetch_run.call_args.kwargs["fetch_run_id"],fetch_run_id)
        self.assertEqual(mock_execute_fetch_run.call_args.kwargs["fetch_options"].maximum_comment_count,5)
        self.assertTrue(mock_execute_fetch_run.call_args.kwargs["fetch_options"].include_replies)
        self.assertEqual(mock_execute_fetch_run.call_args.kwargs["fetch_options"].sort_order,YouTubeCommentSortOrder.NEWEST)


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


    """任務頁應顯示精簡影片資訊與五個靜態分析階段。"""
    def test_analysis_job_detail_page_displays_static_progress_ui(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record)
        response = self.client.get(reverse("analyses:analysis_job_detail",args=[analysis_job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response,"analyses/analysis_job_detail.html")
        self.assertTemplateUsed(response,"analyses/partials/analysis_job_progress_panel.html")
        self.assertEqual(response.context["analysis_job"],analysis_job)
        self.assertEqual([stage.state for stage in response.context["analysis_stages"]],[AnalysisStageState.COMPLETED, AnalysisStageState.CURRENT, AnalysisStageState.WAITING, AnalysisStageState.WAITING, AnalysisStageState.WAITING])
        self.assertContains(response, "準備分析的影片")
        self.assertContains(response, "Selenium")
        self.assertContains(response, "等待處理")
        self.assertContains(response, "1. 確認影片資料")
        self.assertContains(response, "2. 抓取留言")
        self.assertContains(response, "3. 留言清理與正規化")
        self.assertContains(response, "4. AI 情緒與主題分析")
        self.assertContains(response, "5. 建立洞察報告")
        self.assertContains(response, f'href="{reverse("analyses:analysis_job_detail",args=[analysis_job.id])}"')
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "查看分析報告")
        self.assertNotContains(response, "分析紀錄")
        self.assertNotContains(response, "留言探索器")
        self.assertNotContains(response, "任務 ID")
        self.assertNotContains(response, "目前進度")
        self.assertNotContains(response, "0%")

    def test_failed_job_detail_page_displays_failed_stage_and_error_message(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record,status=AnalysisJob.Status.FAILED,current_stage=AnalysisJob.Stage.COMMENT_NORMALIZATION,error_message="模擬留言清理失敗")
        response = self.client.get(reverse("analyses:analysis_job_detail",args=[analysis_job.id]))

        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context["analysis_stages"][2].state,AnalysisStageState.FAILED)
        self.assertContains(response,"模擬留言清理失敗")
        self.assertContains(response,"失敗")

    def test_analysis_job_progress_endpoint_returns_only_progress_panel(self):
        analysis_job = AnalysisJob.objects.create(video=self.video_record)
        response = self.client.get(reverse("analyses:analysis_job_progress",args=[analysis_job.id]))

        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,"analyses/partials/analysis_job_progress_panel.html")
        self.assertTemplateNotUsed(response,"analyses/analysis_job_detail.html")
        self.assertTemplateNotUsed(response,"base.html")
        self.assertEqual(response.context["analysis_job"],analysis_job)
        self.assertEqual(len(response.context["analysis_stages"]),5)
        self.assertContains(response,'id="analysis-job-progress-panel"')

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
        self.analysis_job.refresh_from_db()
        parent_comment = Comment.objects.get(youtube_comment_id="UgzParent123")
        reply_comment = Comment.objects.get(youtube_comment_id="UgzReply123")

        self.assertEqual(fetched_comment_count, 3)
        self.assertEqual(self.fetch_run.fetched_comment_count, 3)
        self.assertEqual(self.analysis_job.current_stage, AnalysisJob.Stage.COMMENT_NORMALIZATION)
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
