"""用标准库验证业务规则；AstrBot 替身不代表真实平台联调。"""

import asyncio
import importlib.util
import json
import re
import sys
import unittest
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


@dataclass
class Plain:
    text: str


@dataclass
class Image:
    path: str

    @classmethod
    def fromFileSystem(cls, path):
        return cls(path)


@dataclass
class Event:
    message_str: str
    is_at_or_wake_command: bool = True
    stopped: bool = False
    extras: dict = field(default_factory=dict)
    sent: list = field(default_factory=list)
    send_error: bool = False
    unified_msg_origin: str = "test-platform:group:session"

    def is_stopped(self):
        return self.stopped

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def plain_result(self, text):
        return text

    def chain_result(self, components):
        return components

    async def send(self, result):
        if self.send_error:
            raise RuntimeError("发送失败")
        self.sent.append(result)

    def stop_event(self):
        self.stopped = True


class Star:
    def __init__(self, context):
        self.context = context


def load_plugin():
    root = Path(__file__).resolve().parents[1]
    package_name = "decision_plugin_under_test"
    package = ModuleType(package_name)
    package.__path__ = [str(root)]

    def command(name, **kwargs):
        def decorate(handler):
            handler.command_name = name
            return handler
        return decorate

    def regex(pattern, **kwargs):
        def decorate(handler):
            handler.pattern = re.compile(pattern)
            return handler
        return decorate

    def custom_filter(cls, **kwargs):
        def decorate(handler):
            handler.awake_filter = cls()
            return handler
        return decorate

    interfaces = {
        package_name: {},
        "astrbot": {},
        "astrbot.api": {"logger": SimpleNamespace(warning=Mock())},
        "astrbot.api.event": {
            "AstrMessageEvent": Event,
            "filter": SimpleNamespace(
                command=command, regex=regex, custom_filter=custom_filter,
                CustomFilter=object,
            ),
        },
        "astrbot.api.star": {"Star": Star, "Context": object},
        "astrbot.api.message_components": {"Plain": Plain, "Image": Image},
    }
    modules = {name: ModuleType(name) for name in interfaces}
    modules[package_name] = package
    for name, attrs in interfaces.items():
        modules[name].__dict__.update(attrs)
    spec = importlib.util.spec_from_file_location(package_name + ".main", root / "main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
        decision = sys.modules[package_name + ".decision"]
    return module, decision


plugin_module, decision = load_plugin()


class DecisionRulesTests(unittest.TestCase):
    def test_exact_probability_and_fixed_answer(self):
        for options, probability, expected in [
            (("A", "B"), 10, {"A": 90, "B": 90, None: 20}),
            (("A", "B", "C"), 10, {"A": 90, "B": 90, "C": 90, None: 30}),
            (("A", "B", "C"), 25, {"A": 75, "B": 75, "C": 75, None: 75}),
            (("A", "B", "C", "D"), 0, {"A": 100, "B": 100, "C": 100, "D": 100}),
            (("A", "B", "C"), 100, {None: 300}),
            (("A", "B", "C", "D"), 50, {"A": 50, "B": 50, "C": 50, "D": 50, None: 200}),
        ]:
            with self.subTest(options=options, probability=probability):
                samples = 100 * len(options)
                with patch.object(decision.random, "randrange", side_effect=range(samples)) as draw:
                    answers = Counter(decision.choose_answer(options, probability) for _ in range(samples))
                self.assertEqual(answers, expected)
                self.assertTrue(all(call.args == (samples,) for call in draw.call_args_list))
        self.assertEqual(decision.BOTH_ANSWER, "两者皆有可能，这就是答案")

    def test_probability_boundaries_and_invalid_configuration(self):
        for probability, roll, expected in [
            (0, 0, "A"), (100, 199, None),
            (-5, 0, "A"), (105, 199, None),
            (None, 19, None), (True, 19, None),
            ("bad", 19, None), (float("nan"), 19, None), (10.5, 19, None),
        ]:
            with self.subTest(probability=probability), patch.object(decision.random, "randrange", return_value=roll):
                self.assertEqual(decision.choose_answer(("A", "B"), probability), expected)

    def test_parses_examples_and_preserves_option_spaces(self):
        for text, expected in [
            ("吃火锅还是吃烤肉", ("吃火锅", "吃烤肉")),
            ("  今天出门 还是 待在家？  ", ("今天出门", "待在家")),
            ("play games | watch a movie?", ("play games", "watch a movie")),
            ("继续 | 还是算了", ("继续", "还是算了")),
            ("A还是B还是C？", ("A", "B", "C")),
            (" A | B | C | D ", ("A", "B", "C", "D")),
        ]:
            with self.subTest(text=text):
                self.assertEqual(decision.parse_options(text), expected)

    def test_rejects_missing_or_empty_options(self):
        for text in ["", "A", "还是B", "A还是？", "A还是还是C", "| B", "A |", "A | | C", "A还是B还是"]:
            with self.subTest(text=text):
                self.assertIsNone(decision.parse_options(text))

    def test_natural_options_accept_exact_spaced_separator_or_help_phrase(self):
        for text, expected in [
            ("A 还是 B", ("A", "B")),
            (" A  还是  B 还是 C？ ", ("A", "B", "C")),
            ("play games 还是 watch a movie。", ("play games", "watch a movie")),
            ("继续 还是 还是算了", ("继续", "还是算了")),
            ("帮我选，A还是B。", ("A", "B")),
            ("帮我选：A还是B还是C？", ("A", "B", "C")),
            ("帮我选 A 还是 B 还是 C", ("A", "B", "C")),
            ("A还是B，帮我选", ("A", "B")),
            ("A还是帮我选，B", ("A", "B")),
            ("A，帮我选还是B", ("A", "B")),
            ("A还是帮我选：B", ("A", "B")),
            ("甲,乙还是帮我选，丙,丁", ("甲,乙", "丙,丁")),
        ]:
            with self.subTest(text=text):
                self.assertEqual(decision.parse_natural_options(text), expected)

    def test_natural_options_reject_partial_spaces_and_empty_options(self):
        for text in ["A还是B", "A 还是B", "A还是 B", "A\t还是\tB",
                     "A\n还是\nB", "帮我选A", " 还是 B", "A 还是 ",
                     "A 还是  还是 C", "A 还是 还是 C", "帮我选，还是B", "帮我选，A还是。",
                     "帮我选，A还是还是C"]:
            with self.subTest(text=text):
                self.assertIsNone(decision.parse_natural_options(text))

    def test_reason_limit_cleanup_and_fallback(self):
        for text, expected in [
            ("因为好" * 5, "因为好" * 5),
            (" 原因：因为很方便 ", "因为很方便"),
            ("“因为适合今天”", "因为适合今天"),
            ("因为好" * 5 + "！", "因为A善"),
            ("", "因为A善"),
            (None, "因为A善"),
            ("很方便\n也有趣", "因为A善"),
            ("我想不出原因", "因为A善"),
        ]:
            with self.subTest(text=text):
                result = decision.normalize_reason(text, "A")
                self.assertEqual(result, expected)
                self.assertLessEqual(len(result), 15)

    def test_long_option_fallback_keeps_format_within_fifteen_characters(self):
        answer = "今天带家人一起出去吃特别好吃的火锅"
        result = decision.fallback_reason(answer)
        self.assertEqual(len(result), 15)
        self.assertTrue(result.startswith("因为"))
        self.assertTrue(result.endswith("…善"))

    def test_templates_randomly_select_one_and_replace_the_option(self):
        templates = ["俺寻思[x]是对的。", "显然[x]更好。"]
        with patch.object(decision.random, "choice", side_effect=templates) as pick:
            replies = [decision.format_answer("吃火锅", templates) for _ in range(2)]
        self.assertEqual(replies, ['俺寻思"吃火锅"是对的。', '显然"吃火锅"更好。'])
        self.assertEqual(pick.call_count, 2)
        self.assertTrue(all(call.args == (templates,) for call in pick.call_args_list))

    def test_invalid_or_empty_templates_fall_back_to_defaults(self):
        for templates in [None, [], "字符串", [None, "", "不含占位符"]]:
            with self.subTest(templates=templates), patch.object(decision.random, "choice", side_effect=lambda items: items[0]):
                self.assertEqual(decision.format_answer("A", templates), '俺寻思"A"是对的。')

    def test_all_placeholders_are_quoted_once_and_answer_is_literal(self):
        answer = r"路径\1"
        for template in ['[x]、"[x]"、“[x]”', '"[x]" 和 "[x]"']:
            with self.subTest(template=template), patch.object(decision.random, "choice", return_value=template):
                rendered = decision.format_answer(answer, [template])
                self.assertEqual(rendered.count(f'"{answer}"'), template.count("[x]"))
                self.assertNotIn('""', rendered)
                self.assertNotIn("[x]", rendered)


class DecisionHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="session-model"),
            llm_generate=AsyncMock(return_value=SimpleNamespace(role="assistant", completion_text="因为合适")),
        )
        self.plugin = plugin_module.DecisionPlugin(self.context)
        template_patch = patch.object(decision.random, "choice", side_effect=lambda items: items[0])
        self.template_choice = template_patch.start()
        self.addCleanup(template_patch.stop)

    async def dispatch_natural(self, event):
        handler = self.plugin.natural_decision
        if handler.pattern.search(event.message_str) and handler.awake_filter.filter(event, None):
            await handler(event)

    def test_legacy_default_templates_upgrade_and_save_without_changing_switches(self):
        class Config(dict):
            save_config = Mock()

        config = Config(reply_templates=["俺寻思[x]是对的。", "显然[x]更好。"],
                        reason_enabled=False, template_enabled=False, send_image=False,
                        special_probability=25)
        plugin_module.DecisionPlugin(self.context, config)
        self.assertEqual(config["reply_templates"], list(decision.DEFAULT_REPLY_TEMPLATES))
        self.assertFalse(config["reason_enabled"])
        self.assertFalse(config["template_enabled"])
        self.assertFalse(config["send_image"])
        self.assertEqual(config["special_probability"], 25)
        config.save_config.assert_called_once_with()

    def test_custom_template_configuration_is_preserved(self):
        custom = ["今日答案：[x]"]
        config = {"reply_templates": custom}
        plugin_module.DecisionPlugin(self.context, config)
        self.assertIs(config["reply_templates"], custom)

    def test_legacy_template_save_failure_still_uses_updated_templates(self):
        class Config(dict):
            save_config = Mock(side_effect=OSError("无法保存"))

        config = Config(reply_templates=["俺寻思[x]是对的。", "显然[x]更好。"])
        with patch.object(plugin_module.logger, "warning") as warning:
            plugin_module.DecisionPlugin(self.context, config)
        self.assertEqual(config["reply_templates"], list(decision.DEFAULT_REPLY_TEMPLATES))
        warning.assert_called_once()

    async def test_command_handles_normalized_prefix_and_full_text(self):
        for text in ["抉择 play games | watch a movie", "/抉择 play games | watch a movie"]:
            with self.subTest(text=text):
                event = Event(text)
                with patch.object(decision.random, "randrange", return_value=20):
                    await self.plugin.decision_command(event)
                self.assertEqual(event.sent, ['当然是选择 "play games"\n俺寻思"play games"是对的。\n因为合适'])
                self.assertTrue(event.stopped)

    async def test_command_all_three_answers(self):
        self.plugin = plugin_module.DecisionPlugin(self.context, {"send_image": False})
        for roll, answer in [(0, "两者皆有可能，这就是答案"), (20, "A"), (110, "B")]:
            with self.subTest(roll=roll):
                event = Event("抉择 A还是B")
                with patch.object(decision.random, "randrange", return_value=roll):
                    await self.plugin.decision_command(event)
                expected = answer if roll == 0 else f'当然是选择 "{answer}"\n俺寻思"{answer}"是对的。\n因为合适'
                self.assertEqual(event.sent, [expected])
                self.assertTrue(event.stopped)

    def assert_special_image(self, event):
        self.assertEqual(len(event.sent), 1)
        chain = event.sent[0]
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0], Plain("两者皆有可能，这就是答案"))
        self.assertIsInstance(chain[1], Image)
        path = Path(chain[1].path)
        expected = Path(__file__).resolve().parents[1] / "assets" / "both_possible.jpg"
        self.assertEqual(path, expected)
        self.assertTrue(path.is_absolute())
        self.assertTrue(path.is_file())
        self.assertTrue(event.stopped)
        self.context.get_current_chat_provider_id.assert_not_awaited()
        self.context.llm_generate.assert_not_awaited()
        self.template_choice.assert_not_called()

    async def test_special_command_attaches_bundled_image_by_default(self):
        event = Event("抉择 A还是B")
        with patch.object(decision.random, "randrange", return_value=0):
            await self.plugin.decision_command(event)
        self.assert_special_image(event)

    async def test_special_natural_question_also_attaches_image(self):
        event = Event("A 还是 B")
        with patch.object(decision.random, "randrange", return_value=0):
            await self.dispatch_natural(event)
        self.assert_special_image(event)

    async def test_disable_image_keeps_special_text_and_skips_image_loading(self):
        self.plugin = plugin_module.DecisionPlugin(None, {"send_image": False})
        event = Event("抉择 A还是B")
        with patch.object(Image, "fromFileSystem") as load_image:
            await self.plugin._respond(event, decision.BOTH_ANSWER, special=True)
        self.assertEqual(event.sent, ["两者皆有可能，这就是答案"])
        self.assertTrue(event.stopped)
        load_image.assert_not_called()

    async def test_normal_answers_and_usage_do_not_load_image(self):
        for answer in ["A", "B", plugin_module._USAGE]:
            with self.subTest(answer=answer):
                event = Event("抉择 A还是B")
                with patch.object(Image, "fromFileSystem") as load_image:
                    await self.plugin._respond(event, answer)
                self.assertEqual(event.sent, [answer])
                load_image.assert_not_called()

    async def test_missing_image_falls_back_to_special_text(self):
        event = Event("抉择 A还是B")
        with patch.object(plugin_module.Path, "is_file", return_value=False), patch.object(plugin_module.logger, "warning") as warning:
            await self.plugin._respond(event, decision.BOTH_ANSWER, special=True)
        self.assertEqual(event.sent, [decision.BOTH_ANSWER])
        self.assertTrue(event.stopped)
        warning.assert_called_once()

    async def test_image_component_failure_falls_back_to_special_text(self):
        event = Event("抉择 A还是B")
        with patch.object(Image, "fromFileSystem", side_effect=ValueError("图片组件无效")), patch.object(plugin_module.logger, "warning") as warning:
            await self.plugin._respond(event, decision.BOTH_ANSWER, special=True)
        self.assertEqual(event.sent, [decision.BOTH_ANSWER])
        self.assertTrue(event.stopped)
        warning.assert_called_once()

    async def test_invalid_command_explains_usage_without_drawing(self):
        for text in ["抉择", "抉择 A", "抉择 A还是", "抉择 A还是还是C"]:
            with self.subTest(text=text):
                event = Event(text)
                with patch.object(decision.random, "randrange") as draw:
                    await self.plugin.decision_command(event)
                self.assertIn("用法：/抉择", event.sent[0])
                self.assertTrue(event.stopped)
                draw.assert_not_called()

    async def test_awake_natural_question_returns_one_answer(self):
        event = Event("吃火锅 还是 吃烤肉？")
        with patch.object(decision.random, "randrange", return_value=199):
            await self.dispatch_natural(event)
        self.assertEqual(event.sent, ['当然是选择 "吃烤肉"\n俺寻思"吃烤肉"是对的。\n因为合适'])
        self.assertTrue(event.stopped)

    async def test_unawakened_group_message_is_ignored(self):
        event = Event("吃火锅 还是 吃烤肉？", is_at_or_wake_command=False)
        with patch.object(decision.random, "randrange") as draw:
            await self.dispatch_natural(event)
        self.assertEqual(event.sent, [])
        self.assertFalse(event.stopped)
        draw.assert_not_called()

    async def test_natural_handler_ignores_commands_and_invalid_input(self):
        for text in ["抉择 A 还是 B", "/别的命令 A 还是 B", "A 还是  还是 C", " 还是 B", "A 还是 ？", "帮我选，A | 还是算了"]:
            with self.subTest(text=text):
                event = Event(text)
                with patch.object(decision.random, "randrange") as draw:
                    await self.dispatch_natural(event)
                self.assertEqual(event.sent, [])
                self.assertFalse(event.stopped)
                draw.assert_not_called()

    async def test_natural_handler_yields_to_matched_normalized_commands(self):
        # WakingCheckStage 会先去掉 /，再写入已匹配命令的参数映射。
        for text, params in [
            ("echo A 还是 B", {}),
            ("tools echo 帮我选，A还是B", {"text": "帮我选，A还是B"}),
        ]:
            with self.subTest(text=text):
                event = Event(text, extras={"handlers_parsed_params": {"other.handler": params}})
                with patch.object(decision.random, "randrange", return_value=20) as draw:
                    await self.dispatch_natural(event)
                self.assertEqual(event.sent, [])
                self.assertFalse(event.stopped)
                draw.assert_not_called()

    async def test_duplicate_response_and_stopped_event_do_not_send_again(self):
        event = Event("抉择 A还是B")
        await self.plugin._respond(event, "A")
        await self.plugin._respond(event, "B")
        self.assertEqual(event.sent, ["A"])
        stopped = Event("抉择 A还是B", stopped=True)
        await self.plugin._respond(stopped, "B")
        self.assertEqual(stopped.sent, [])

    async def test_send_failure_still_stops_followup_processing(self):
        event = Event("抉择 A还是B", send_error=True)
        with self.assertRaisesRegex(RuntimeError, "发送失败"):
            await self.plugin._respond(event, "A")
        self.assertTrue(event.stopped)

    async def test_uses_current_session_model_and_keeps_selected_answer(self):
        event = Event("抉择 吃火锅还是吃烤肉")
        self.context.llm_generate.return_value.completion_text = "因为暖和又热闹"
        with patch.object(decision.random, "randrange", return_value=20):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, ['当然是选择 "吃火锅"\n俺寻思"吃火锅"是对的。\n因为暖和又热闹'])
        self.context.get_current_chat_provider_id.assert_awaited_once_with(umo=event.unified_msg_origin)
        self.context.llm_generate.assert_awaited_once()
        kwargs = self.context.llm_generate.call_args.kwargs
        self.assertEqual(kwargs["chat_provider_id"], "session-model")
        self.assertEqual(json.loads(kwargs["prompt"]), {"选项": ["吃火锅", "吃烤肉"], "所选答案": "吃火锅"})
        self.assertIn("因为吃火锅善", kwargs["system_prompt"])
        self.assertNotIn("contexts", kwargs)
        self.assertNotIn("tools", kwargs)

    async def test_bad_model_outputs_use_selected_option_fallback(self):
        for output in ["", "原" * 16, "有趣\n好吃", "不好想原因", None]:
            with self.subTest(output=output):
                self.context.llm_generate.return_value.completion_text = output
                event = Event("抉择 吃火锅还是吃烤肉")
                with patch.object(decision.random, "randrange", return_value=110):
                    await self.plugin.decision_command(event)
                self.assertEqual(event.sent, ['当然是选择 "吃烤肉"\n俺寻思"吃烤肉"是对的。\n因为吃烤肉善'])
                self.assertTrue(event.stopped)

    async def test_missing_current_model_and_generation_error_fall_back(self):
        for stage in ["get_current_chat_provider_id", "llm_generate"]:
            with self.subTest(stage=stage):
                self.context.get_current_chat_provider_id.side_effect = None
                self.context.llm_generate.side_effect = None
                getattr(self.context, stage).side_effect = RuntimeError("提供商不可用")
                event = Event("抉择 A还是B")
                with patch.object(decision.random, "randrange", return_value=20), patch.object(plugin_module.logger, "warning"):
                    await self.plugin.decision_command(event)
                self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。\n因为A善'])
                self.assertTrue(event.stopped)

    async def test_timeout_falls_back_without_hanging(self):
        async def wait_forever(**kwargs):
            await asyncio.Future()

        self.context.llm_generate.side_effect = wait_forever
        event = Event("抉择 A还是B")
        with patch.object(plugin_module, "_REASON_TIMEOUT_SECONDS", 0.01), patch.object(decision.random, "randrange", return_value=20), patch.object(plugin_module.logger, "warning"):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。\n因为A善'])
        self.assertTrue(event.stopped)

    async def test_model_error_role_does_not_become_a_reason(self):
        self.context.llm_generate.return_value = SimpleNamespace(role="err", completion_text="API error")
        event = Event("抉择 A还是B")
        with patch.object(decision.random, "randrange", return_value=20):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。\n因为A善'])

    async def test_no_model_call_for_usage_special_or_stopped_event(self):
        await self.plugin.decision_command(Event("抉择"))
        with patch.object(decision.random, "randrange", return_value=0):
            await self.plugin.decision_command(Event("抉择 A还是B"))
        await self.plugin._respond(Event("A还是B", stopped=True), "A", ("A", "B"))
        self.context.get_current_chat_provider_id.assert_not_awaited()
        self.context.llm_generate.assert_not_awaited()

    async def test_duplicate_callbacks_call_model_only_once(self):
        event = Event("抉择 A还是B")
        await self.plugin._respond(event, "A", ("A", "B"))
        await self.plugin._respond(event, "A", ("A", "B"))
        self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。\n因为合适'])
        self.context.llm_generate.assert_awaited_once()

    async def test_stopping_during_model_generation_prevents_late_reply(self):
        event = Event("抉择 A还是B")

        async def generate(**kwargs):
            event.stop_event()
            return SimpleNamespace(role="assistant", completion_text="因为合适")

        self.context.llm_generate.side_effect = generate
        with patch.object(decision.random, "randrange", return_value=20):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, [])

    async def test_long_option_fallback_preserves_full_selected_answer(self):
        answer = "今天带家人一起出去吃特别好吃的火锅"
        self.context.llm_generate.return_value.completion_text = ""
        event = Event(f"抉择 {answer}还是B")
        with patch.object(decision.random, "randrange", return_value=20):
            await self.plugin.decision_command(event)
        selected, template, reason = event.sent[0].split("\n")
        self.assertEqual(selected, f'当然是选择 "{answer}"')
        self.assertEqual(template, f'俺寻思"{answer}"是对的。')
        self.assertEqual(reason, decision.fallback_reason(answer))
        self.assertLessEqual(len(reason), 15)

    async def test_disabled_reason_skips_model_in_command_and_natural_question(self):
        self.plugin = plugin_module.DecisionPlugin(self.context, {"reason_enabled": False})
        for text, handler in [
            ("抉择 A还是B", self.plugin.decision_command),
            ("A 还是 B", self.dispatch_natural),
        ]:
            with self.subTest(text=text):
                event = Event(text)
                with patch.object(decision.random, "randrange", return_value=20):
                    await handler(event)
                self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。'])
                self.assertTrue(event.stopped)
        self.context.get_current_chat_provider_id.assert_not_awaited()
        self.context.llm_generate.assert_not_awaited()

    async def test_custom_template_keeps_option_and_independent_reason_toggle(self):
        self.plugin = plugin_module.DecisionPlugin(
            self.context,
            {"reply_templates": ["无占位符", "今日答案：[x]"], "reason_enabled": False},
        )
        event = Event("抉择 吃火锅还是吃烤肉")
        with patch.object(decision.random, "randrange", return_value=110):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, ['当然是选择 "吃烤肉"\n今日答案："吃烤肉"'])
        self.context.llm_generate.assert_not_awaited()

    async def test_special_answer_ignores_custom_templates_and_reason_setting(self):
        self.plugin = plugin_module.DecisionPlugin(
            self.context,
            {"reply_templates": ["答案：[x]"], "reason_enabled": True, "send_image": False},
        )
        event = Event("抉择 A还是B")
        with patch.object(decision.random, "randrange", return_value=0):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, [decision.BOTH_ANSWER])
        self.context.llm_generate.assert_not_awaited()
        self.template_choice.assert_not_called()

    async def test_option_colliding_with_fixed_text_is_still_a_normal_choice(self):
        for text, roll in [
            (f"抉择 {decision.BOTH_ANSWER}还是B", 20),
            (f"抉择 A还是{decision.BOTH_ANSWER}", 110),
        ]:
            with self.subTest(text=text):
                self.context.llm_generate.reset_mock()
                self.template_choice.reset_mock()
                event = Event(text)
                with patch.object(decision.random, "randrange", return_value=roll), patch.object(Image, "fromFileSystem") as image:
                    await self.plugin.decision_command(event)
                self.assertEqual(event.sent, [f'当然是选择 "{decision.BOTH_ANSWER}"\n俺寻思"{decision.BOTH_ANSWER}"是对的。\n因为合适'])
                self.context.llm_generate.assert_awaited_once()
                self.template_choice.assert_called_once()
                image.assert_not_called()

    async def test_three_choices_work_in_commands_and_natural_questions(self):
        self.plugin = plugin_module.DecisionPlugin(self.context, {"reason_enabled": False})
        for text, handler in [
            ("抉择 A还是B还是C", self.plugin.decision_command),
            ("A 还是 B 还是 C？", self.dispatch_natural),
            ("帮我选，A还是B还是C。", self.dispatch_natural),
            ("抉择 A | B | C", self.plugin.decision_command),
        ]:
            for roll, answer in [(30, "A"), (120, "B"), (210, "C")]:
                with self.subTest(text=text, roll=roll):
                    event = Event(text)
                    with patch.object(decision.random, "randrange", return_value=roll):
                        await handler(event)
                    self.assertEqual(event.sent, [f'当然是选择 "{answer}"\n俺寻思"{answer}"是对的。'])
                    self.assertTrue(event.stopped)
        self.context.llm_generate.assert_not_awaited()

    async def test_three_choice_reason_receives_all_options(self):
        event = Event("抉择 A还是B还是C")
        with patch.object(decision.random, "randrange", return_value=210):
            await self.plugin.decision_command(event)
        self.assertEqual(event.sent, ['当然是选择 "C"\n俺寻思"C"是对的。\n因为合适'])
        data = json.loads(self.context.llm_generate.call_args.kwargs["prompt"])
        self.assertEqual(data, {"选项": ["A", "B", "C"], "所选答案": "C"})

    async def test_configurable_special_probability_in_both_handlers(self):
        for probability, expected in [(0, '当然是选择 "A"'), (100, decision.BOTH_ANSWER)]:
            for text, handler in [
                ("抉择 A还是B还是C", self.plugin.decision_command),
                ("A 还是 B 还是 C", self.dispatch_natural),
            ]:
                with self.subTest(probability=probability, text=text):
                    self.plugin.config = {
                        "special_probability": probability,
                        "reason_enabled": False, "template_enabled": False,
                        "send_image": False,
                    }
                    event = Event(text)
                    with patch.object(decision.random, "randrange", return_value=0):
                        await handler(event)
                    self.assertEqual(event.sent, [expected])
                    self.assertTrue(event.stopped)
        self.context.llm_generate.assert_not_awaited()
        self.template_choice.assert_not_called()

    async def test_template_and_reason_switches_are_independent(self):
        for template_enabled, reason_enabled, expected in [
            (False, False, '当然是选择 "C"'),
            (True, False, '当然是选择 "C"\n今日答案："C"'),
            (False, True, '当然是选择 "C"\n因为合适'),
            (True, True, '当然是选择 "C"\n今日答案："C"\n因为合适'),
        ]:
            with self.subTest(template=template_enabled, reason=reason_enabled):
                self.context.llm_generate.reset_mock()
                self.context.get_current_chat_provider_id.reset_mock()
                self.template_choice.reset_mock()
                self.plugin.config = {
                    "template_enabled": template_enabled,
                    "reason_enabled": reason_enabled,
                    "reply_templates": ["今日答案：[x]"],
                }
                event = Event("抉择 A还是B还是C")
                with patch.object(decision.random, "randrange", return_value=210):
                    await self.plugin.decision_command(event)
                self.assertEqual(event.sent, [expected])
                self.assertEqual(self.template_choice.call_count, int(template_enabled))
                self.assertEqual(self.context.llm_generate.await_count, int(reason_enabled))
                self.assertEqual(self.context.get_current_chat_provider_id.await_count, int(reason_enabled))

    async def test_unawakened_three_option_question_is_ignored(self):
        for text in ["A 还是 B 还是 C", "帮我选，A还是B还是C"]:
            with self.subTest(text=text):
                event = Event(text, is_at_or_wake_command=False)
                with patch.object(decision.random, "randrange") as draw:
                    await self.dispatch_natural(event)
                self.assertEqual(event.sent, [])
                self.assertFalse(event.stopped)
                draw.assert_not_called()

    async def test_unspaced_questions_do_not_match_regex_or_direct_handler(self):
        for text in ["A还是B", "A 还是B", "A还是 B", "A\t还是\tB",
                     "A\n还是\nB", "帮我选A", "今天还是待在家"]:
            with self.subTest(text=text):
                self.assertIsNone(self.plugin.natural_decision.pattern.search(text))
                event = Event(text)
                with patch.object(decision.random, "randrange") as draw:
                    await self.dispatch_natural(event)
                    await self.plugin.natural_decision(event)
                self.assertEqual(event.sent, [])
                self.assertFalse(event.stopped)
                draw.assert_not_called()
        self.context.llm_generate.assert_not_awaited()

    async def test_help_phrase_is_removed_before_choice_and_model_prompt(self):
        for text in ["帮我选，A还是B。", "帮我选:A还是B", "A还是B，帮我选",
                     "A还是帮我选，B", "A，帮我选还是B", "A还是帮我选：B"]:
            with self.subTest(text=text):
                self.context.llm_generate.reset_mock()
                event = Event(text)
                with patch.object(decision.random, "randrange", return_value=20):
                    await self.dispatch_natural(event)
                self.assertEqual(event.sent, ['当然是选择 "A"\n俺寻思"A"是对的。\n因为合适'])
                data = json.loads(self.context.llm_generate.call_args.kwargs["prompt"])
                self.assertEqual(data, {"选项": ["A", "B"], "所选答案": "A"})

    async def test_help_phrase_special_answer_still_attaches_image(self):
        event = Event("帮我选，A还是B。")
        with patch.object(decision.random, "randrange", return_value=0):
            await self.dispatch_natural(event)
        self.assert_special_image(event)


if __name__ == "__main__":
    unittest.main()
