from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.account_service import account_service as global_account_service
from services.auth_service import AuthService
from services.config import config
from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI
from services.storage.json_storage import JSONStorageBackend
from utils.helper import anonymize_token, split_image_model


class ImageModelSlugTests(unittest.TestCase):
    def test_uses_account_default_model_slug_when_present(self) -> None:
        with patch.object(
                global_account_service, "get_account",
                return_value={"default_model_slug": "gpt-5-5-thinking"},
        ):
            self.assertEqual(
                OpenAIBackendAPI(access_token="t1")._image_model_slug("gpt-image-2"),
                "gpt-5-5-thinking",
            )

    def test_falls_back_to_auto_without_default_model_slug(self) -> None:
        with patch.object(global_account_service, "get_account", return_value={}):
            self.assertEqual(
                OpenAIBackendAPI(access_token="t2")._image_model_slug("gpt-image-2"),
                "auto",
            )

    def test_codex_branch_is_unaffected(self) -> None:
        with patch.object(
                global_account_service, "get_account",
                return_value={"default_model_slug": "gpt-5-5-thinking"},
        ):
            self.assertEqual(
                OpenAIBackendAPI(access_token="t1")._image_model_slug("codex-gpt-image-2"),
                "codex-gpt-image-2",
            )


class AccountCapabilityTests(unittest.TestCase):
    def test_unknown_quota_accounts_are_available_only_when_not_throttled(self) -> None:
        self.assertFalse(
            AccountService._is_image_account_available(
                {"status": "限流", "image_quota_unknown": True, "quota": 0}
            )
        )
        self.assertTrue(
            AccountService._is_image_account_available(
                {"status": "正常", "image_quota_unknown": True, "quota": 0}
            )
        )

    def test_prolite_variants_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            self.assertEqual(service._normalize_account_type("prolite"), "ProLite")
            self.assertEqual(service._normalize_account_type("pro_lite"), "ProLite")

    def test_search_account_type_ignores_unrelated_scalar_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            self.assertIsNone(
                service._search_account_type(
                    {
                        "amr": ["pwd", "otp", "mfa"],
                        "chatgpt_compute_residency": "no_constraint",
                        "chatgpt_data_residency": "no_constraint",
                        "user_id": "user-I52GFfLGFM0dokFk2dBiKEBn",
                    }
                )
            )

    def test_mark_image_result_does_not_consume_unknown_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_accounts(["token-1"])
            service.update_account(
                "token-1",
                {
                    "status": "正常",
                    "quota": 0,
                    "image_quota_unknown": True,
                },
            )

            updated = service.mark_image_result("token-1", success=True)

            self.assertIsNotNone(updated)
            self.assertEqual(updated["quota"], 0)
            self.assertEqual(updated["status"], "正常")
            self.assertTrue(updated["image_quota_unknown"])

    def test_split_image_model_supports_plan_type_prefix(self) -> None:
        self.assertEqual(split_image_model("gpt-image-2"), (None, "gpt-image-2"))
        self.assertEqual(split_image_model("plus-codex-gpt-image-2"), ("plus", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("team-codex-gpt-image-2"), ("team", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("pro-codex-gpt-image-2"), ("pro", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("plus-gpt-image-2"), (None, None))
        self.assertEqual(split_image_model("unknown-image-model"), (None, None))

    def test_get_available_access_token_filters_by_plan_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items(
                [
                    {"access_token": "token-plus", "type": "Plus", "status": "正常", "quota": 3},
                    {"access_token": "token-pro", "type": "Pro", "status": "正常", "quota": 3},
                ]
            )

            service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

            plus_token = service.get_available_access_token(plan_type="plus")
            pro_token = service.get_available_access_token(plan_type="pro")
            service.release_image_slot(plus_token)
            service.release_image_slot(pro_token)

            self.assertEqual(plus_token, "token-plus")
            self.assertEqual(pro_token, "token-pro")

    def test_prefers_plan_type_returns_immediately_when_no_preferred_account_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-free", "type": "free", "status": "正常", "quota": 3},
            ])
            service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

            start = time.monotonic()
            token = service.get_available_access_token_preferring_plan_types(
                preferred_plan_types=("plus", "team", "pro"), wait_secs=5.0,
            )
            elapsed = time.monotonic() - start

            self.assertEqual(token, "token-free")
            self.assertLess(elapsed, 1.0)

    def test_prefers_plan_type_picks_idle_preferred_account_over_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-free", "type": "free", "status": "正常", "quota": 3},
                {"access_token": "token-plus", "type": "Plus", "status": "正常", "quota": 3},
            ])
            service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

            token = service.get_available_access_token_preferring_plan_types(
                preferred_plan_types=("plus", "team", "pro"), wait_secs=1.0,
            )

            self.assertEqual(token, "token-plus")

    def test_prefers_plan_type_falls_back_to_free_after_wait_when_preferred_busy(self) -> None:
        original_concurrency = config.data.get("image_account_concurrency")
        config.data["image_account_concurrency"] = 1
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
                service.add_account_items([
                    {"access_token": "token-free", "type": "free", "status": "正常", "quota": 3},
                    {"access_token": "token-plus", "type": "Plus", "status": "正常", "quota": 3},
                ])
                service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

                # 占满 Plus 账号唯一的并发槽位，使其暂时不可用
                busy_token = service.get_available_access_token(plan_types=("plus", "team", "pro"))
                self.assertEqual(busy_token, "token-plus")

                start = time.monotonic()
                token = service.get_available_access_token_preferring_plan_types(
                    preferred_plan_types=("plus", "team", "pro"), wait_secs=0.3,
                )
                elapsed = time.monotonic() - start

                self.assertEqual(token, "token-free")
                self.assertGreaterEqual(elapsed, 0.25)
        finally:
            if original_concurrency is None:
                config.data.pop("image_account_concurrency", None)
            else:
                config.data["image_account_concurrency"] = original_concurrency

    def test_prefers_plan_type_waits_for_preferred_account_to_free_up(self) -> None:
        original_concurrency = config.data.get("image_account_concurrency")
        config.data["image_account_concurrency"] = 1
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
                service.add_account_items([
                    {"access_token": "token-free", "type": "free", "status": "正常", "quota": 3},
                    {"access_token": "token-plus", "type": "Plus", "status": "正常", "quota": 3},
                ])
                service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

                busy_token = service.get_available_access_token(plan_types=("plus", "team", "pro"))
                self.assertEqual(busy_token, "token-plus")

                def _release_shortly() -> None:
                    time.sleep(0.15)
                    service.release_image_slot(busy_token)

                releaser = Thread(target=_release_shortly)
                releaser.start()
                try:
                    token = service.get_available_access_token_preferring_plan_types(
                        preferred_plan_types=("plus", "team", "pro"), wait_secs=2.0,
                    )
                finally:
                    releaser.join()

                self.assertEqual(token, "token-plus")
        finally:
            if original_concurrency is None:
                config.data.pop("image_account_concurrency", None)
            else:
                config.data["image_account_concurrency"] = original_concurrency

    def test_refresh_accounts_can_remove_invalid_token_without_confirmation_delay(self) -> None:
        original_value = config.data.get("auto_remove_invalid_accounts")
        config.data["auto_remove_invalid_accounts"] = True
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
                service.add_account_items([{"access_token": "invalid-token", "status": "正常"}])

                with patch(
                    "services.openai_backend_api.OpenAIBackendAPI.get_user_info",
                    side_effect=InvalidAccessTokenError("token invalidated (/backend-api/me)"),
                ):
                    result = service.refresh_accounts(["invalid-token"], defer_invalid_removal=False)

                self.assertEqual(result["refreshed"], 0)
                self.assertEqual(len(result["errors"]), 1)
                self.assertEqual(result["items"], [])
                self.assertIsNone(service.get_account("invalid-token"))
        finally:
            if original_value is None:
                config.data.pop("auto_remove_invalid_accounts", None)
            else:
                config.data["auto_remove_invalid_accounts"] = original_value

    def test_refresh_accounts_defers_invalid_token_removal_by_default(self) -> None:
        original_value = config.data.get("auto_remove_invalid_accounts")
        config.data["auto_remove_invalid_accounts"] = True
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
                service.add_account_items([{"access_token": "invalid-token", "status": "正常"}])

                with patch(
                    "services.openai_backend_api.OpenAIBackendAPI.get_user_info",
                    side_effect=InvalidAccessTokenError("token invalidated (/backend-api/me)"),
                ):
                    result = service.refresh_accounts(["invalid-token"])

                account = service.get_account("invalid-token")
                self.assertEqual(result["refreshed"], 0)
                self.assertEqual(len(result["errors"]), 1)
                self.assertIsNotNone(account)
                self.assertEqual(account["invalid_count"], 1)
        finally:
            if original_value is None:
                config.data.pop("auto_remove_invalid_accounts", None)
            else:
                config.data["auto_remove_invalid_accounts"] = original_value


class TokenLogTests(unittest.TestCase):
    def test_anonymize_token_hides_raw_value(self) -> None:
        token = "super-secret-token"
        token_ref = anonymize_token(token)

        self.assertTrue(token_ref.startswith("token:"))
        self.assertNotIn(token, token_ref)


class AuthServiceTests(unittest.TestCase):
    def test_create_authenticate_disable_and_delete_user_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))

            item, raw_key = service.create_key(role="user", name="Alice")

            self.assertEqual(item["role"], "user")
            self.assertEqual(item["name"], "Alice")
            self.assertTrue(item["enabled"])
            self.assertTrue(raw_key.startswith("sk-"))

            authed = service.authenticate(raw_key)
            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])
            self.assertEqual(authed["role"], "user")
            self.assertIsNotNone(authed["last_used_at"])

            updated = service.update_key(item["id"], {"enabled": False}, role="user")
            self.assertIsNotNone(updated)
            self.assertFalse(updated["enabled"])
            self.assertIsNone(service.authenticate(raw_key))

            self.assertTrue(service.delete_key(item["id"], role="user"))
            self.assertFalse(service.delete_key(item["id"], role="user"))
            self.assertEqual(service.list_keys(role="user"), [])

    def test_authenticate_ignores_last_used_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, raw_key = service.create_key(role="user", name="Alice")

            def fail_save() -> None:
                raise OSError("disk unavailable")

            service._save = fail_save

            authed = service.authenticate(raw_key)

            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])
            self.assertIsNotNone(authed["last_used_at"])

    def test_update_user_key_replaces_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, raw_key = service.create_key(role="user", name="Alice")

            updated = service.update_key(item["id"], {"key": "sk-user-custom-key"}, role="user")

            self.assertIsNotNone(updated)
            self.assertIsNone(service.authenticate(raw_key))

            authed = service.authenticate("sk-user-custom-key")
            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])

    def test_user_key_name_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            first, _ = service.create_key(role="user", name="Alice")
            second, _ = service.create_key(role="user", name="Bob")

            with self.assertRaisesRegex(ValueError, "这个名称已经在使用中了"):
                service.create_key(role="user", name="Alice")

            with self.assertRaisesRegex(ValueError, "这个名称已经在使用中了"):
                service.update_key(second["id"], {"name": "Alice"}, role="user")

            updated = service.update_key(first["id"], {"name": "Alice"}, role="user")
            self.assertIsNotNone(updated)
            self.assertEqual(updated["name"], "Alice")


if __name__ == "__main__":
    unittest.main()
