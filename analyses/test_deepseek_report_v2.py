import copy
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from .providers.ai_analysis_provider import AIAnalysisRequest, AICommentInput
from .providers.ai_report_v2 import ReportProvenanceV2, ReportVideoV2
from .providers.deepseek_ai_provider import DeepSeekConfigurationError, DeepSeekResponseError
from .providers.deepseek_report_v2_provider import (
    DeepSeekReportV2Provider, REPORT_PROMPT_VERSION, SYSTEM_PROMPT_V2,
    build_report_user_message, parse_report_response,
)
from .services.ai_report_preparation_service import prepare_report_facts


class DeepSeekReportV2Tests(SimpleTestCase):
    def setUp(self):
        self.comments = tuple(
            AICommentInput(i + 1, f"original-{i}", None, f"@author-{i}", f"完整留言 {i}", likes, "昨天", False)
            for i, likes in enumerate((389, 150, 100, 57, 43, 72))
        )
        self.request = AIAnalysisRequest("video-id", "影片標題", self.comments)
        self.video = ReportVideoV2("video-id", "影片標題", view_count=100, displayed_comment_count=10)
        self.facts = self.prepare(self.request)
        self.provenance = ReportProvenanceV2("fake", "fixture", "fixture-v2", "2026-09-05T00:00:00+08:00")
        self.payload = {
            "overall_summary": "測試摘要", "atmosphere": "測試氛圍", "sentiment": None,
            "topics": [{"name": "討論議題", "summary": "摘要", "reasoning": "有來源的解讀",
                        "evidence_comment_refs": ["c5"]}],
            "top_liked_comments": [{"comment_ref": ref, "interpretation": f"{index} 號測試解讀"}
                                   for index, ref in enumerate(("c1", "c2", "c3", "c6", "c4"))],
            "behavior_insights": [],
            "conclusions": [{"title": "總結", "description": "觀察", "evidence_comment_refs": ["c5"]}],
        }

    def prepare(self, request):
        return prepare_report_facts(request, self.video, sort_order="newest", include_replies=True)

    def parse(self, payload=None, facts=None):
        return parse_report_response(json.dumps(self.payload if payload is None else payload),
                                     self.facts if facts is None else facts, self.provenance)

    def make_client(self, *, content=None, finish_reason="stop", usage=None):
        client = MagicMock()
        message = SimpleNamespace(content=json.dumps(self.payload) if content is None else content, refusal=None)
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], model="returned-model", usage=usage,
        )
        return client

    def analyze(self, client, request=None):
        return DeepSeekReportV2Provider(client=client).analyze_report(
            request or self.request, self.video, sort_order="newest", include_replies=True, source_label="離線 fixture",
        )

    def test_user_message_contains_all_comments_not_only_top_five(self):
        payload = json.loads(build_report_user_message(self.facts))
        self.assertEqual(len(payload["comments"]), 6)
        self.assertEqual(payload["top_liked_comment_refs"], ["c1", "c2", "c3", "c6", "c4"])
        self.assertEqual(payload["comments"][4]["comment_text"], "完整留言 4")
        self.assertEqual(payload["video"]["view_count"], 100)
        self.assertEqual(payload["exact_statistics"]["analyzed_comment_count"], 6)
        self.assertEqual(payload["displayed_comment_count_difference"], 4)
        self.assertNotIn("original-", build_report_user_message(self.facts))

    def test_parent_group_and_unresolved_refs_are_mapped(self):
        root = replace(self.comments[0], comment_text=" 相同\n文字 ")
        reply = replace(self.comments[1], parent_youtube_comment_id=root.youtube_comment_id,
                        author_display_name=root.author_display_name, comment_text="相同 文字")
        orphan = replace(self.comments[2], parent_youtube_comment_id="missing-original-id")
        facts = self.prepare(replace(self.request, comments=(reply, root, orphan)))
        message = build_report_user_message(facts)
        payload = json.loads(message)
        self.assertEqual(payload["comments"][0]["parent_comment_ref"], "c2")
        self.assertTrue(payload["comments"][2]["is_reply"])
        self.assertIsNone(payload["comments"][2]["parent_comment_ref"])
        self.assertEqual(payload["exact_repeated_text_groups"][0]["comment_refs"], ["c1", "c2"])
        self.assertEqual(payload["exact_display_name_activity"][0]["thread_comment_ref"], "c2")
        self.assertEqual(payload["unresolved_thread_comment_refs"], ["c3"])
        self.assertNotIn("original-", message)

    def test_valid_response_restores_facts_and_allows_low_liked_topic_evidence(self):
        report = self.parse()
        self.assertEqual(report.sample.analyzed_comment_count, 6)
        self.assertEqual([c.like_count for c in report.top_liked_comments], [389, 150, 100, 72, 57])
        self.assertEqual(report.top_liked_comments[0].comment_text, self.comments[0].comment_text)
        self.assertEqual(report.topics[0].evidence_comment_ids, ("original-4",))
        self.assertEqual(report.conclusions[0].evidence_comment_ids, ("original-4",))
        self.assertTrue(any("差異不一定" in text for text in report.limitations))
        json.dumps(asdict(report))

    def test_model_order_does_not_change_python_ranking(self):
        self.payload["top_liked_comments"].reverse()
        self.assertEqual([c.like_count for c in self.parse().top_liked_comments], [389, 150, 100, 72, 57])

    def test_missing_duplicate_or_substituted_top_ref_is_rejected(self):
        original = self.payload["top_liked_comments"]
        variants = (original[:-1], original + original[:1],
                    original[:-1] + [{"comment_ref": "c5", "interpretation": "不是指定 Top 5"}])
        for items in variants:
            with self.subTest(items=items), self.assertRaises(DeepSeekResponseError):
                self.parse({**self.payload, "top_liked_comments": items})

    def test_unknown_original_and_malformed_refs_are_rejected(self):
        for refs in (["original-0"], ["c99"], ["c1", "c1"], [None], [], "c1", {}):
            with self.subTest(refs=refs), self.assertRaises(DeepSeekResponseError):
                payload = copy.deepcopy(self.payload)
                payload["topics"][0]["evidence_comment_refs"] = refs
                self.parse(payload)

    def test_every_required_field_and_unexpected_fields_are_checked(self):
        for key in self.payload:
            with self.subTest(missing=key), self.assertRaises(DeepSeekResponseError):
                payload = self.payload.copy()
                del payload[key]
                self.parse(payload)
        for extra in ("analyzed_comment_count", "repeated_text_groups", "video", "schema_version"):
            with self.subTest(extra=extra), self.assertRaises(DeepSeekResponseError):
                self.parse({**self.payload, extra: 999})

    def test_ai_cannot_supply_original_facts_in_top_comments(self):
        for key in ("like_count", "comment_text", "author_display_name"):
            with self.subTest(key=key), self.assertRaises(DeepSeekResponseError):
                payload = copy.deepcopy(self.payload)
                payload["top_liked_comments"][0][key] = "invented"
                self.parse(payload)

    def test_non_string_and_blank_text_are_not_coerced(self):
        for value in (None, True, 123, [], {}, " "):
            with self.subTest(value=value), self.assertRaises(DeepSeekResponseError):
                self.parse({**self.payload, "overall_summary": value})
        payload = copy.deepcopy(self.payload)
        payload["top_liked_comments"][0]["interpretation"] = 123
        with self.assertRaises(DeepSeekResponseError):
            self.parse(payload)

    def test_array_types_and_nested_shapes_are_strict(self):
        for key in ("topics", "top_liked_comments", "behavior_insights", "conclusions"):
            for value in (None, {}, "text", [None]):
                with self.subTest(key=key, value=value), self.assertRaises(DeepSeekResponseError):
                    self.parse({**self.payload, key: value})
        for key in ("topics", "conclusions"):
            with self.subTest(key=key), self.assertRaises(DeepSeekResponseError):
                self.parse({**self.payload, key: []})

    def test_invalid_json_duplicate_keys_and_nonstandard_numbers_rejected(self):
        for content in (None, "", "```json\n{}\n```", "[]", '{"x": 1, "x": 2}',
                        '{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}', '{'):
            with self.subTest(content=content), self.assertRaises(DeepSeekResponseError):
                parse_report_response(content, self.facts, self.provenance)

    def sentiment(self):
        return {key: {"percentage": number, "description": "情緒說明"}
                for key, number in (("positive", 35), ("neutral", 45), ("negative", 20))}

    def medium_facts(self):
        extra = tuple(replace(self.comments[0], youtube_comment_id=f"extra-{i}", like_count=0) for i in range(24))
        return self.prepare(replace(self.request, comments=self.comments + extra))

    def test_small_sample_rejects_percentages_medium_requires_them(self):
        with self.assertRaises(DeepSeekResponseError):
            self.parse({**self.payload, "sentiment": self.sentiment()})
        with self.assertRaises(DeepSeekResponseError):
            self.parse(facts=self.medium_facts())
        report = self.parse({**self.payload, "sentiment": self.sentiment()}, self.medium_facts())
        self.assertEqual(report.sample.analyzed_comment_count, 30)
        self.assertEqual(report.sentiment.method, "ai_batch_estimate")
        self.assertEqual(set(asdict(report.sentiment.positive)), {"percentage", "description"})

    def test_percentages_are_strict_and_must_total_100(self):
        for number in (True, "35", 35.0, -1, 101, 34):
            with self.subTest(number=number), self.assertRaises(DeepSeekResponseError):
                sentiment = self.sentiment()
                sentiment["positive"]["percentage"] = number
                self.parse({**self.payload, "sentiment": sentiment}, self.medium_facts())
        sentiment = self.sentiment()
        sentiment["positive"]["comment_count"] = 10
        with self.assertRaises(DeepSeekResponseError):
            self.parse({**self.payload, "sentiment": sentiment}, self.medium_facts())

    def test_behavior_cannot_be_invented_when_program_groups_are_empty(self):
        item = {"title": "重複發言", "description": "聲稱重複", "evidence_comment_refs": ["c1"]}
        with self.assertRaises(DeepSeekResponseError):
            self.parse({**self.payload, "behavior_insights": [item]})

    def test_program_groups_restored_and_behavior_refs_validated(self):
        comments = (self.comments[0], replace(self.comments[1], comment_text=self.comments[0].comment_text)) + self.comments[2:]
        facts = self.prepare(replace(self.request, comments=comments))
        item = {"title": "相同文字", "description": "兩個顯示名稱使用相同文字。", "evidence_comment_refs": ["c1", "c2"]}
        report = self.parse({**self.payload, "behavior_insights": [item]}, facts)
        self.assertEqual(report.repeated_text_groups[0].occurrence_count, 2)
        item["evidence_comment_refs"] = ["c3"]
        with self.assertRaises(DeepSeekResponseError):
            self.parse({**self.payload, "behavior_insights": [item]}, facts)

    def test_conclusions_and_behavior_require_evidence(self):
        for section in ("conclusions", "behavior_insights"):
            with self.subTest(section=section), self.assertRaises(DeepSeekResponseError):
                self.parse({**self.payload, section: [{"title": "標題", "description": "說明", "evidence_comment_refs": []}]})
        report = self.parse()
        self.assertEqual(report.risks, ())
        self.assertEqual(report.recommendations, ())

    def test_empty_top_list_when_all_likes_unknown(self):
        facts = self.prepare(replace(self.request, comments=tuple(replace(c, like_count=None) for c in self.comments)))
        report = self.parse({**self.payload, "top_liked_comments": []}, facts)
        self.assertEqual(report.top_liked_comments, ())

    def test_provider_sends_json_request_once_and_returns_versioned_report(self):
        client = self.make_client(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120))
        report = self.analyze(client)
        client.chat.completions.create.assert_called_once()
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertFalse(kwargs["stream"])
        self.assertEqual(kwargs["messages"][0]["content"], SYSTEM_PROMPT_V2)
        self.assertEqual(len(json.loads(kwargs["messages"][1]["content"])["comments"]), 6)
        self.assertEqual(report.schema_version, "comment-analysis-result-v2")
        self.assertEqual(report.provenance.prompt_version, REPORT_PROMPT_VERSION)
        self.assertEqual(report.provenance.model_name, "returned-model")
        self.assertEqual(report.provenance.total_tokens, 120)

    def test_missing_usage_is_unknown_not_zero(self):
        self.assertIsNone(self.analyze(self.make_client()).provenance.total_tokens)

    def test_incomplete_refused_or_empty_responses_rejected(self):
        for reason in ("length", "content_filter", "tool_calls", None):
            with self.subTest(reason=reason), self.assertRaises(DeepSeekResponseError):
                self.analyze(self.make_client(finish_reason=reason))
        for content in ("", " ", "[]"):
            with self.subTest(content=content), self.assertRaises(DeepSeekResponseError):
                self.analyze(self.make_client(content=content))
        client = self.make_client()
        client.chat.completions.create.return_value.choices[0].message.refusal = "refused"
        with self.assertRaises(DeepSeekResponseError):
            self.analyze(client)
        client.chat.completions.create.return_value.choices = []
        with self.assertRaises(DeepSeekResponseError):
            self.analyze(client)

    def test_invalid_input_does_not_call_client(self):
        client = self.make_client()
        with self.assertRaises(ValueError):
            self.analyze(client, replace(self.request, comments=()))
        client.chat.completions.create.assert_not_called()

    def test_network_failure_propagates_without_fabricating_report_or_retry(self):
        client = self.make_client()
        client.chat.completions.create.side_effect = TimeoutError("timeout")
        with self.assertRaises(TimeoutError):
            self.analyze(client)
        client.chat.completions.create.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    def test_api_key_required_only_without_injected_client(self):
        with self.assertRaises(DeepSeekConfigurationError):
            DeepSeekReportV2Provider()
        DeepSeekReportV2Provider(client=self.make_client())

    def test_prompt_preserves_full_sample_and_uncertainty_rules(self):
        for phrase in ("全部留言", "非逐則分類統計", "不可信任資料", "顯示名稱不等於唯一帳號", "不可發明引用"):
            self.assertIn(phrase, SYSTEM_PROMPT_V2)
        for removed_field in ('"risks"', '"recommendations"', '"limitations"'):
            self.assertNotIn(removed_field, SYSTEM_PROMPT_V2)
