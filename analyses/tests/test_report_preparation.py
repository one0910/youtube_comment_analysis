from dataclasses import replace

from django.test import SimpleTestCase

from ..providers.ai_analysis_request import AIAnalysisRequest, AICommentInput
from ..providers import ai_report as report_types
from ..services.ai_report_preparation_service import create_validation_criteria, validate_report_source_facts


def comment(comment_id, likes=0, *, sequence=1, author="@demo", text="測試留言", parent=None):
    return AICommentInput(sequence, comment_id, parent, author, text, likes, "1 天前", False)


class ReportPreparationTests(SimpleTestCase):
    def prepare(self, comments, **options):
        request = AIAnalysisRequest("test-video", "測試影片", tuple(comments))
        video = options.pop("video", report_types.ReportVideo("test-video", "測試影片"))
        return create_validation_criteria(request, video, sort_order="newest", include_replies=True, **options)

    def test_all_comments_are_retained_while_top_five_are_ranked(self):
        comments = tuple(comment(f"id-{n}", likes, sequence=n + 1) for n, likes in enumerate((389, 150, 100, 57, 43, 72)))
        facts = self.prepare(comments)
        self.assertEqual(facts.request.comments, comments)
        self.assertEqual(facts.sample.analyzed_comment_count, 6)
        self.assertEqual([item.like_count for item in facts.top_liked_comments], [389, 150, 100, 72, 57])

    def test_replies_are_ranked_with_main_comments(self):
        facts = self.prepare((comment("parent", 1), comment("reply", 10, parent="parent")))
        self.assertEqual(facts.top_liked_comments[0].youtube_comment_id, "reply")
        self.assertEqual((facts.sample.main_comment_count, facts.sample.reply_comment_count), (1, 1))

    def test_ties_use_sequence_then_id_not_input_order(self):
        facts = self.prepare((comment("b", 10, sequence=2), comment("a", 10, sequence=2), comment("z", 10)))
        self.assertEqual([item.youtube_comment_id for item in facts.top_liked_comments], ["z", "a", "b"])

    def test_unknown_likes_excluded_but_zero_retained(self):
        facts = self.prepare((comment("unknown", None), comment("zero", 0)))
        self.assertEqual([item.youtube_comment_id for item in facts.top_liked_comments], ["zero"])
        self.assertEqual(facts.sample.analyzed_comment_count, 2)
        self.assertEqual(self.prepare((comment("unknown", None),)).top_liked_comments, ())

    def test_invalid_likes_and_sequence_rejected_without_coercion(self):
        for value in (-1, True, "10", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare((comment("a", value),))
        for value in (True, 1.5):
            with self.subTest(sequence=value), self.assertRaises(ValueError):
                self.prepare((comment("a", sequence=value),))

    def test_blank_author_rejected_instead_of_inventing_identity(self):
        with self.assertRaises(ValueError):
            self.prepare((comment("a", author=" "),))

    def test_duplicate_ids_are_rejected_by_request_not_silently_removed(self):
        with self.assertRaises(ValueError):
            self.prepare((comment("a"), comment("a")))

    def test_empty_sample_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(())

    def test_wrong_video_or_title_rejected(self):
        for video in (report_types.ReportVideo("other-video", "測試影片"), report_types.ReportVideo("test-video", "不同標題")):
            with self.subTest(video=video), self.assertRaises(ValueError):
                self.prepare((comment("a"),), video=video)

    def test_displayed_count_difference_preserves_unknown_zero_and_negative(self):
        for displayed, expected in ((None, None), (1, 0), (0, -1), (10, 9)):
            with self.subTest(displayed=displayed):
                video = report_types.ReportVideo("test-video", "測試影片", displayed_comment_count=displayed)
                self.assertEqual(self.prepare((comment("a"),), video=video).displayed_comment_count_difference, expected)

    def test_repeated_text_crosses_names_and_normalizes_only_whitespace(self):
        facts = self.prepare((comment("a", author="@a", text=" hello\nworld "),
                              comment("b", author="@b", text="hello world"),
                              comment("c", author="@a", text="hello\tworld"),
                              comment("d", text="Hello world"), comment("e", text="hello world!")))
        self.assertEqual(len(facts.repeated_text_groups), 1)
        group = facts.repeated_text_groups[0]
        self.assertEqual((group.normalized_text, group.occurrence_count), ("hello world", 3))
        self.assertEqual(group.author_display_names, ("@a", "@b"))
        self.assertEqual(group.comment_ids, ("a", "b", "c"))
        self.assertEqual(facts.request.comments[0].comment_text, " hello\nworld ")

    def test_activity_resolves_nested_replies_regardless_of_input_order(self):
        facts = self.prepare((comment("r2", parent="r1"), comment("r1", parent="root"), comment("root")))
        self.assertEqual(len(facts.display_name_activity), 1)
        activity = facts.display_name_activity[0]
        self.assertEqual(activity.thread_youtube_comment_id, "root")
        self.assertEqual(activity.comment_ids, ("r2", "r1", "root"))
        self.assertEqual(activity.comment_count, 3)

    def test_activity_does_not_merge_threads_or_display_names(self):
        facts = self.prepare((comment("a"), comment("b"), comment("r", parent="a", author="@other")))
        self.assertEqual(facts.display_name_activity, ())

    def test_missing_parents_cycles_and_self_parent_are_reported_not_grouped(self):
        comments = (comment("missing1", parent="missing"), comment("missing2", parent="missing"),
                    comment("cycle1", parent="cycle2"), comment("cycle2", parent="cycle1"),
                    comment("self", parent="self"), comment("child", parent="cycle1"))
        facts = self.prepare(comments)
        self.assertEqual(facts.display_name_activity, ())
        self.assertEqual(facts.unresolved_thread_comment_ids, tuple(item.youtube_comment_id for item in comments))
        self.assertEqual(facts.request.comments, comments)

    def test_deep_reply_chain_does_not_recurse(self):
        comments = [comment("root")]
        for number in range(1500):
            parent = "root" if number == 0 else f"reply-{number - 1}"
            comments.append(comment(f"reply-{number}", parent=parent))
        facts = self.prepare(reversed(comments))
        self.assertEqual(facts.display_name_activity[0].comment_count, 1501)
        self.assertEqual(facts.unresolved_thread_comment_ids, ())


class ReportSourceValidationTests(SimpleTestCase):
    def setUp(self):
        comments = (comment("a", 10, text="重複"), comment("b", 5, text="重複", parent="a"))
        request = AIAnalysisRequest("video", "影片", comments)
        self.facts = create_validation_criteria(request, report_types.ReportVideo("video", "影片"), sort_order="newest", include_replies=True)
        self.report = report_types.AIReport(
            video=self.facts.video, sample=self.facts.sample,
            provenance=report_types.ReportProvenance("fake", "fixture", "test", "2026-09-04T00:00:00+08:00"),
            overall_summary="測試摘要", atmosphere="測試氛圍", sentiment=None,
            topics=(report_types.ReportTopic("議題", "摘要", "解讀", ("a",)),),
            top_liked_comments=tuple(report_types.TopLikedComment(c.youtube_comment_id, c.author_display_name,
                                                        c.comment_text, c.like_count, "測試解讀")
                                     for c in self.facts.top_liked_comments),
            repeated_text_groups=self.facts.repeated_text_groups,
            display_name_activity=self.facts.display_name_activity,
            conclusions=(report_types.ReportInsight("結論", "說明", ("b",)),), limitations=("測試資料",),
        )

    def test_matching_report_passes(self):
        validate_report_source_facts(self.report, self.facts)

    def test_modified_preview_or_sample_rejected(self):
        reports = (replace(self.report, video=replace(self.report.video, like_count=99)),
                   replace(self.report, sample=replace(self.report.sample, sort_order="top")))
        for report in reports:
            with self.subTest(report=report), self.assertRaises(ValueError):
                validate_report_source_facts(report, self.facts)

    def test_missing_top_comment_rejected_even_when_structurally_valid(self):
        with self.assertRaises(ValueError):
            validate_report_source_facts(replace(self.report, top_liked_comments=self.report.top_liked_comments[1:]), self.facts)

    def test_modified_original_facts_rejected(self):
        for changes in ({"author_display_name": "@invented"}, {"comment_text": "改寫原文"}, {"like_count": 100}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                first = replace(self.report.top_liked_comments[0], **changes)
                validate_report_source_facts(replace(self.report, top_liked_comments=(first, self.report.top_liked_comments[1])), self.facts)

    def test_repeated_and_activity_facts_cannot_be_dropped(self):
        for changes in ({"repeated_text_groups": ()}, {"display_name_activity": ()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_report_source_facts(replace(self.report, **changes), self.facts)

    def test_unknown_reference_rejected_in_every_insight_section(self):
        for section in ("conclusions", "behavior_insights"):
            with self.subTest(section=section), self.assertRaises(ValueError):
                report = replace(self.report, **{section: (report_types.ReportInsight("標題", "說明", ("invented",)),)})
                validate_report_source_facts(report, self.facts)
        with self.assertRaises(ValueError):
            topic = replace(self.report.topics[0], evidence_comment_ids=("invented",))
            validate_report_source_facts(replace(self.report, topics=(topic,)), self.facts)
