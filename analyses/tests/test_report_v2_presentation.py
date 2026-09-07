from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.shortcuts import render
from django.urls import NoReverseMatch, include, path, reverse

from .. import urls as analyses_urls
from ..services.report_v2_presentation_service import build_report_context
from .report_v2_factory import build_report_test_fixture


def report_template_test_view(request):
    report, facts = build_report_test_fixture(small=request.GET.get("sample") == "small")
    return render(request, "analyses/report_v2.html", build_report_context(report, facts))


urlpatterns = [
    path("", include(([
        path("__test__/report/", report_template_test_view, name="analysis_report_detail"),
        *analyses_urls.urlpatterns,
    ], "analyses"), namespace="analyses")),
]


@override_settings(ROOT_URLCONF=__name__)
class ReportV2PresentationTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("analyses:analysis_report_detail")

    @patch("analyses.providers.deepseek_report_v2_provider.DeepSeekReportV2Provider.analyze_report")
    def test_report_template_uses_fixture_without_api_or_database(self, analyze):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "analyses/report_v2.html")
        self.assertContains(response, "影片分析報告 | TubeSense AI")
        self.assertEqual(response.context["report"].sample.analyzed_comment_count, 30)
        self.assertEqual([c.like_count for c in response.context["report"].top_liked_comments], [389, 150, 100, 72, 57])
        analyze.assert_not_called()

    def test_development_preview_routes_are_removed(self):
        for name in ("report_v2_preview", "report_v2_real_preview"):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(f"analyses:{name}")
        self.assertEqual(self.client.get("/analyses/reports/preview/v2/").status_code, 404)
        self.assertEqual(self.client.get("/analyses/reports/preview/v2/real/").status_code, 404)

    def test_all_report_sections_render(self):
        response = self.client.get(self.url)
        for text in ("情緒分析概況", "核心脈絡拆解", "影片最高讚留言TOP5", "重複內容與活躍發言觀察",
                     "總結與核心觀察", "查看引用原文", "片長 未知"):
            self.assertContains(response, text)
        self.assertNotContains(response, "69 則")
        self.assertNotContains(response, "全場最高共鳴")
        for removed_text in ("Python 統計 · 相同文字", "Python 統計 · 討論串參與",
                             "風險提示", "後續建議", "分析限制與資料來源", "Token：輸入"):
            self.assertNotContains(response, removed_text)

    def test_evidence_links_follow_descriptions_inline(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-testid="behavior-description-with-evidence"')
        self.assertContains(response, 'data-testid="insight-description-with-evidence"')
        self.assertContains(response, 'data-testid="inline-evidence"')
        self.assertContains(response, '<details class="group inline text-sm"')
        self.assertNotContains(response, '<details class="mt-4 text-sm"')

    def test_leaderboard_has_no_interpretation_disclosure_or_second_author_line(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "查看解讀")
        self.assertNotContains(response, "留言訊息 / 解讀")
        self.assertNotContains(response, "<small>本次樣本最高讚</small>")
        self.assertContains(response, "工具能節省時間，但不能省略資料來源的查證。")
        self.assertContains(response, 'aria-label="高讚留言表格"')
        self.assertContains(response, "table-fixed")
        self.assertContains(response, "[overflow-wrap:anywhere]")
        self.assertNotContains(response, "min-w-[900px]")
        self.assertNotContains(response, "overflow-x-auto")

    def test_leaderboard_uses_mobile_cards_and_desktop_table(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-testid="mobile-leaderboard"')
        self.assertContains(response, 'data-testid="mobile-leaderboard-card"', count=5)
        self.assertContains(response, 'data-testid="desktop-leaderboard"')
        self.assertContains(response, 'class="hidden lg:block"')
        self.assertContains(response, '高讚數代表意見解讀（風向指標）')
        self.assertContains(response, '[overflow-wrap:anywhere]')

    def test_topic_evidence_shows_comment_and_like_count_without_author(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        topics_html = html.split('aria-labelledby="topics-title"', 1)[1].split('aria-labelledby="top-title"', 1)[0]
        self.assertIn('data-testid="topic-evidence-row"', topics_html)
        self.assertIn('data-testid="topic-evidence-like"', topics_html)
        self.assertIn("按讚數", topics_html)
        self.assertIn("389 讚", topics_html)
        self.assertNotIn("@示範觀眾_01", topics_html)
        self.assertEqual(topics_html.count('data-testid="topic-evidence-divider"'), 5)
        self.assertEqual(topics_html.count('data-visible="true"'), 3)
        self.assertEqual(topics_html.count('data-visible="false"'), 2)

    def test_sentiment_chart_has_accessible_percentages_not_counts(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'aria-label="AI 估計：正面 35%、中立 45%、負面 20%"')
        self.assertContains(response, 'stroke-dasharray="35 100"')
        self.assertContains(response, 'stroke-dashoffset="-35"')
        self.assertContains(response, "非逐則分類統計")

    def test_small_sample_has_text_only_and_empty_behavior_states(self):
        response = self.client.get(self.url, {"sample": "small"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "小型樣本，以文字描述為主")
        self.assertContains(response, "3 則留言")
        self.assertEqual(response.context["report"].sample.top_level_comment_count, 3)
        self.assertEqual(response.context["report"].sample.reply_comment_count, 0)
        self.assertEqual(response.context["report"].repeated_text_groups, ())
        self.assertNotContains(response, 'data-testid="sentiment-donut"')
        self.assertIsNone(response.context["report"].sentiment)
        self.assertContains(response, "Top 3")
        self.assertNotContains(response, "重複內容與活躍發言觀察")
        self.assertNotContains(response, "Behavioral Observations")

    def test_small_context_caps_historical_insights_and_hides_behavior(self):
        report, facts = build_report_test_fixture(small=True)
        report = replace(
            report,
            topics=report.topics + (report.topics[0],),
            conclusions=report.conclusions + (report.conclusions[0],),
            behavior_insights=(report.conclusions[0],),
        )

        context = build_report_context(report, facts)

        self.assertEqual(len(context["topic_panels"]), 2)
        self.assertEqual(len(context["conclusion_panels"]), 2)
        self.assertEqual(context["behavior_panels"], [])
        self.assertFalse(context["show_behavior_section"])

    def test_render_escapes_analysis_and_source_text(self):
        report, facts = build_report_test_fixture()
        attack = '<script>alert("x")</script>'
        report = replace(report, overall_summary=attack)
        with patch("analyses.tests.test_report_v2_presentation.build_report_test_fixture", return_value=(report, facts)):
            response = self.client.get(self.url)
        self.assertNotContains(response, attack)
        self.assertContains(response, "&lt;script&gt;")

    def test_context_resolves_real_evidence_and_guards_source_facts(self):
        report, facts = build_report_test_fixture()
        context = build_report_context(report, facts)
        self.assertEqual(context["topic_panels"][0]["evidence"][0].comment_text, facts.request.comments[0].comment_text)
        self.assertEqual(context["report"].repeated_text_groups[0].occurrence_count, 2)
        with self.assertRaises(ValueError):
            build_report_context(replace(report, video=replace(report.video, view_count=999)), facts)

    def test_context_replaces_historical_internal_refs_with_author_names(self):
        report, facts = build_report_test_fixture()
        topic = replace(report.topics[0], reasoning="c1 與 c2 都提到人工核對。")

        context = build_report_context(replace(report, topics=(topic,)), facts)

        reasoning = context["topic_panels"][0]["item"].reasoning
        self.assertEqual(reasoning, "@示範觀眾_01 與 @示範觀眾_02 都提到人工核對。")
        self.assertNotIn("c1", reasoning)
        self.assertNotIn("c2", reasoning)

    def test_topic_panels_show_at_most_three_representative_comments(self):
        report, facts = build_report_test_fixture()
        topic = replace(report.topics[0], evidence_comment_ids=("demo-1", "demo-2", "demo-3", "demo-4"))
        context = build_report_context(replace(report, topics=(topic,)), facts)
        self.assertEqual([comment.youtube_comment_id for comment in context["topic_panels"][0]["evidence"]],
                         ["demo-1", "demo-2", "demo-3"])

    def test_unknown_video_counts_are_displayed_as_unknown_not_none_or_zero(self):
        report, facts = build_report_test_fixture()
        video = replace(report.video, view_count=None, like_count=None, displayed_comment_count=None)
        with patch("analyses.tests.test_report_v2_presentation.build_report_test_fixture", return_value=(replace(report, video=video), replace(facts, video=video))):
            response = self.client.get(self.url)
        self.assertContains(response, "影片按讚 未知")
        self.assertContains(response, "YouTube 顯示留言 未知")
        self.assertNotContains(response, ">None<")

    def test_page_uses_project_tailwind_bundle_without_standalone_stylesheet(self):
        response = self.client.get(self.url)
        self.assertContains(response, '/static/css/app.css')
        self.assertNotContains(response, 'report-v2.css')

    def test_report_navigation_is_highlighted_in_desktop_and_mobile_sidebars(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-testid="desktop-report-nav"')
        self.assertContains(response, 'data-testid="mobile-report-nav"')
        self.assertContains(response, 'aria-current="page"', count=2)

    def test_sample_notice_uses_medium_mode_wording_without_fetch_details(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-testid="sample-notice"')
        self.assertContains(response, "中型樣本模式（情況 B）", count=1)
        self.assertContains(response, "本次分析 <strong class=\"font-bold text-brand-navy\">30 則留言</strong>")
        self.assertContains(response, "（含 <strong")
        self.assertContains(response, "20 則主留言")
        self.assertContains(response, "10 則回覆")
        self.assertNotContains(response, "30 至 200 筆")
        self.assertNotContains(response, "排序：")
        self.assertNotContains(response, "YouTube 顯示數 − 本次分析數")

    def test_small_sample_notice_uses_small_mode_wording(self):
        response = self.client.get(self.url, {"sample": "small"})
        self.assertContains(response, "小型樣本模式（情況 A）", count=1)
        self.assertContains(response, "本次分析 <strong class=\"font-bold text-brand-navy\">3 則留言</strong>")

    def test_template_syntax_is_not_emitted_as_plain_text(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "{%")
        self.assertNotContains(response, "%}")
        self.assertNotContains(response, "{{")
        self.assertNotContains(response, "}}")
