"""新版契約的離線測試，不建立資料庫、不呼叫 AI。"""

import json
from dataclasses import asdict, replace

from django.test import SimpleTestCase

from ..providers import ai_report as report_types


class AIReportContractTests(SimpleTestCase):
    def setUp(self):
        self.sentiment = report_types.SentimentEstimate(
            positive=report_types.SentimentCategory(35, "部分留言肯定影片的說明。"),
            neutral=report_types.SentimentCategory(45, "部分留言討論內容或提出問題。"),
            negative=report_types.SentimentCategory(20, "部分留言表達不滿。"),
        )
        self.report = report_types.AIReport(
            video=report_types.ReportVideo("example-video", "契約測試影片"),
            sample=report_types.ReportSample(30, 20, 10, "newest", True),
            provenance=report_types.ReportProvenance("fake", "fixture", "fixture", "2026-09-04T12:00:00+08:00"),
            overall_summary="僅供格式測試，不是真實分析。",
            atmosphere="以討論內容為主，並有不同看法。",
            sentiment=self.sentiment,
            topics=(report_types.ReportTopic("內容說明", "討論說明方式。", "留言提到說明清楚。", ("id-1",)),),
            top_liked_comments=(report_types.TopLikedComment("id-1", "@demo", "說明清楚。", 10, "肯定說明方式。"),),
            conclusions=(report_types.ReportInsight("主要觀察", "樣本有正向回饋。", ("id-1",)),),
            limitations=("測試資料，不代表真實留言。",),
        )

    def test_report_serializes_version_and_estimate_without_sentiment_counts(self):
        payload = json.loads(json.dumps(asdict(self.report), ensure_ascii=False))
        self.assertEqual(payload["schema_version"], "comment-analysis-result")
        self.assertEqual(payload["sample"]["analysis_mode"], "medium")
        self.assertEqual(payload["sentiment"]["method"], "ai_batch_estimate")
        self.assertIn("非逐則分類統計", payload["sentiment"]["notice"])
        for category in ("positive", "neutral", "negative"):
            self.assertEqual(set(payload["sentiment"][category]), {"percentage", "description"})

    def test_mode_boundaries_are_calculated_by_program(self):
        for count, mode in ((1, "small"), (29, "small"), (30, "medium"), (200, "medium"), (201, "large")):
            with self.subTest(count=count):
                sample = report_types.ReportSample(count, count, 0, "newest", False)
                self.assertEqual(sample.analysis_mode, mode)

    def test_small_sample_requires_null_sentiment_but_keeps_atmosphere(self):
        sample = report_types.ReportSample(2, 2, 0, "top", False)
        report = replace(self.report, sample=sample, sentiment=None)
        self.assertTrue(report.atmosphere)
        with self.assertRaises(ValueError):
            replace(report, sentiment=self.sentiment)

    def test_medium_and_large_require_sentiment(self):
        for count in (30, 200, 201):
            with self.subTest(count=count), self.assertRaises(ValueError):
                replace(self.report, sample=report_types.ReportSample(count, count, 0, "top", False), sentiment=None)

    def test_percentages_reject_bool_strings_floats_and_out_of_range(self):
        for value in (True, "35", 35.5, -1, 101):
            with self.subTest(value=value), self.assertRaises(ValueError):
                report_types.SentimentCategory(value, "情緒說明")

    def test_percentages_must_total_100_and_have_descriptions(self):
        with self.assertRaises(ValueError):
            replace(self.sentiment, positive=report_types.SentimentCategory(34, "說明"))
        with self.assertRaises(ValueError):
            report_types.SentimentCategory(35, "  ")

    def test_sample_rejects_inconsistent_negative_or_empty_counts(self):
        for counts in ((0, 0, 0), (30, 20, 9), (30, 31, -1), (True, 1, 0), (30.0, 20, 10)):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                report_types.ReportSample(*counts, "newest", True)

    def test_sample_rejects_invalid_fetch_options(self):
        for options in (("invalid", True), ("newest", "yes"), ("newest", False)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                report_types.ReportSample(30, 20, 10, *options)

    def test_unknown_preview_values_are_null_not_zero(self):
        payload = asdict(self.report.video)
        for name in ("view_count", "like_count", "published_at", "duration_seconds", "captured_at"):
            self.assertIsNone(payload[name])
        self.assertEqual(replace(self.report.video, like_count=0).like_count, 0)
        with self.assertRaises(ValueError):
            replace(self.report.video, view_count=-1)

    def test_timestamps_require_timezone_and_valid_iso_format(self):
        for timestamp in ("昨天", "2026-09-04T12:00:00", ""):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                replace(self.report.provenance, generated_at=timestamp)

    def test_topic_requires_reasoning_and_unique_nonempty_evidence(self):
        topic = self.report.topics[0]
        for evidence in ((), ("",), ("id-1", "id-1"), "id-1"):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                replace(topic, evidence_comment_ids=evidence)
        with self.assertRaises(ValueError):
            replace(topic, reasoning="")

    def test_general_recommendations_can_omit_evidence(self):
        insight = report_types.ReportInsight("管理建議", "持續留意留言區的人身攻擊。")
        self.assertEqual(insight.evidence_comment_ids, ())

    def test_top_liked_comments_reject_wrong_order_duplicates_and_over_five(self):
        first = self.report.top_liked_comments[0]
        higher = replace(first, youtube_comment_id="id-2", like_count=20)
        for comments in ((first, higher), (first, first),
                         tuple(replace(first, youtube_comment_id=f"id-{n}") for n in range(6))):
            with self.subTest(comments=comments), self.assertRaises(ValueError):
                replace(self.report, top_liked_comments=comments)
        self.assertEqual(len(replace(self.report, top_liked_comments=(higher, first)).top_liked_comments), 2)

    def test_unknown_likes_are_not_ranked_and_empty_top_list_is_allowed(self):
        with self.assertRaises(ValueError):
            replace(self.report.top_liked_comments[0], like_count=None)
        self.assertEqual(replace(self.report, top_liked_comments=()).top_liked_comments, ())

    def test_repetition_supports_different_display_names_and_derives_count(self):
        group = report_types.RepeatedTextGroup("相同文字", ("@a", "@b"), ("id-1", "id-2", "id-3"))
        self.assertEqual(group.occurrence_count, 3)
        self.assertEqual(len(group.author_display_names), 2)
        for ids in (("id-1",), ("id-1", "id-1")):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                replace(group, comment_ids=ids)

    def test_activity_is_scoped_to_display_name_and_thread(self):
        activity = report_types.DisplayNameActivity("@a", "parent-id", ("reply-1", "reply-2"))
        self.assertEqual(activity.comment_count, 2)
        self.assertEqual(activity.thread_youtube_comment_id, "parent-id")
        with self.assertRaises(ValueError):
            replace(activity, comment_ids=("reply-1",))
        self.assertIn("顯示名稱不等於唯一帳號", self.report.identity_notice)

    def test_list_inputs_are_frozen_and_wrong_nested_types_rejected(self):
        topics = list(self.report.topics)
        report = replace(self.report, topics=topics)
        topics.clear()
        self.assertEqual(len(report.topics), 1)
        with self.assertRaises(ValueError):
            replace(self.report, topics=({"name": "不是 DTO"},))
        with self.assertRaises(ValueError):
            replace(self.report, video={})

    def test_report_requires_limitations(self):
        for limitations in ((), ("",), "不是清單"):
            with self.subTest(limitations=limitations), self.assertRaises(ValueError):
                replace(self.report, limitations=limitations)
