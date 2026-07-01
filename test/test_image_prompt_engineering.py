from __future__ import annotations

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config
from services.protocol import conversation as conversation_module
from services.protocol.conversation import conversation_events, engineer_image_prompt


class ImagePromptEngineeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_enabled = config.data.get("image_prompt_engineering_enabled")
        self._original_prompt = config.data.get("image_prompt_engineering_prompt")
        self._original_timeout = config.data.get("image_prompt_engineering_timeout_secs")

    def tearDown(self) -> None:
        self._restore("image_prompt_engineering_enabled", self._original_enabled)
        self._restore("image_prompt_engineering_prompt", self._original_prompt)
        self._restore("image_prompt_engineering_timeout_secs", self._original_timeout)

    def _restore(self, key: str, value) -> None:
        if value is None:
            config.data.pop(key, None)
        else:
            config.data[key] = value

    def test_disabled_by_default_returns_prompt_unchanged_without_calling_collect_text(self) -> None:
        config.data["image_prompt_engineering_enabled"] = False
        with mock.patch.object(conversation_module, "collect_text") as mock_collect:
            result = engineer_image_prompt("画一只猫")
        self.assertEqual(result, "画一只猫")
        mock_collect.assert_not_called()

    def test_enabled_uses_rewritten_prompt(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        with mock.patch.object(conversation_module, "collect_text", return_value="a detailed rewritten prompt"), \
             mock.patch.object(conversation_module, "text_backend", return_value=object()):
            result = engineer_image_prompt("画一只猫")
        self.assertEqual(result, "a detailed rewritten prompt")

    def test_enabled_falls_back_to_original_prompt_on_exception(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        with mock.patch.object(conversation_module, "collect_text", side_effect=RuntimeError("boom")), \
             mock.patch.object(conversation_module, "text_backend", return_value=object()):
            result = engineer_image_prompt("画一只猫")
        self.assertEqual(result, "画一只猫")

    def test_enabled_falls_back_to_original_prompt_on_timeout(self) -> None:
        # image_prompt_engineering_timeout_secs 属性下限是 1.0 秒，直接打桩属性本身
        # 绕开这个下限，避免测试为了触发超时而真的等待 1 秒以上。
        config.data["image_prompt_engineering_enabled"] = True

        def _slow_collect_text(*_args, **_kwargs):
            time.sleep(0.3)
            return "too late"

        with mock.patch.object(type(config), "image_prompt_engineering_timeout_secs", new_callable=mock.PropertyMock, return_value=0.05), \
             mock.patch.object(conversation_module, "collect_text", side_effect=_slow_collect_text), \
             mock.patch.object(conversation_module, "text_backend", return_value=object()):
            result = engineer_image_prompt("画一只猫")
        self.assertEqual(result, "画一只猫")

    def test_empty_rewrite_result_falls_back_to_original_prompt(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        with mock.patch.object(conversation_module, "collect_text", return_value="   "), \
             mock.patch.object(conversation_module, "text_backend", return_value=object()):
            result = engineer_image_prompt("画一只猫")
        self.assertEqual(result, "画一只猫")

    def test_conversation_events_skips_engineering_when_disabled(self) -> None:
        config.data["image_prompt_engineering_enabled"] = False
        backend = mock.MagicMock()
        backend.stream_conversation.return_value = iter([])
        with mock.patch.object(conversation_module, "engineer_image_prompt") as mock_engineer:
            list(conversation_events(backend, prompt="画一只猫", model="gpt-image-2"))
        mock_engineer.assert_not_called()

    def test_conversation_events_skips_engineering_for_codex_model(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        backend = mock.MagicMock()
        backend.stream_conversation.return_value = iter([])
        with mock.patch.object(conversation_module, "engineer_image_prompt") as mock_engineer:
            list(conversation_events(backend, prompt="画一只猫", model="codex-gpt-image-2"))
        mock_engineer.assert_not_called()

    def test_conversation_events_skips_engineering_when_images_present(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        backend = mock.MagicMock()
        backend.stream_conversation.return_value = iter([])
        with mock.patch.object(conversation_module, "engineer_image_prompt") as mock_engineer:
            list(conversation_events(backend, prompt="画一只猫", model="gpt-image-2", images=["data:image/png;base64,abc"]))
        mock_engineer.assert_not_called()

    def test_conversation_events_engineers_prompt_for_plain_image_request(self) -> None:
        config.data["image_prompt_engineering_enabled"] = True
        backend = mock.MagicMock()
        backend.stream_conversation.return_value = iter([])
        with mock.patch.object(conversation_module, "engineer_image_prompt", return_value="rewritten") as mock_engineer:
            list(conversation_events(backend, prompt="画一只猫", model="gpt-image-2"))
        mock_engineer.assert_called_once_with("画一只猫")
        backend._report_progress.assert_any_call("engineering_prompt")


if __name__ == "__main__":
    unittest.main()
