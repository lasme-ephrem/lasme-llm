import unittest

from core.inference.profiles import (
    GEMMA_CHAT_PROFILE,
    GEMMA_FABLE_PROFILE,
    get_model_profile,
)


class ModelProfileTests(unittest.TestCase):
    def test_selects_chat_profile_with_or_without_latest_tag(self):
        self.assertIs(
            get_model_profile("gemma-4-chat"),
            GEMMA_CHAT_PROFILE,
        )
        self.assertIs(
            get_model_profile("gemma-4-chat:latest"),
            GEMMA_CHAT_PROFILE,
        )

    def test_selects_fable_profile_with_or_without_latest_tag(self):
        self.assertIs(
            get_model_profile("gemma-4-fable"),
            GEMMA_FABLE_PROFILE,
        )
        self.assertIs(
            get_model_profile("gemma-4-fable:latest"),
            GEMMA_FABLE_PROFILE,
        )

    def test_selects_fast_and_vision_profiles(self):
        fast = get_model_profile("lasme-smol-fast")
        vision = get_model_profile("lasme-qwen-vision")
        self.assertLess(fast.num_ctx, GEMMA_CHAT_PROFILE.num_ctx)
        self.assertFalse(fast.think)
        self.assertFalse(vision.think)
        self.assertIn("Vision", vision.system_addendum)

    def test_profiles_use_full_power_settings(self):
        for profile in (GEMMA_CHAT_PROFILE, GEMMA_FABLE_PROFILE):
            self.assertEqual(profile.num_ctx, 65_536)
            self.assertEqual(profile.num_predict, 8_192)
            self.assertEqual(profile.history_tokens, 48_000)
            self.assertTrue(profile.think)
            self.assertTrue(profile.system_addendum)
            self.assertEqual(profile.options["top_p"], 0.95)
            self.assertEqual(profile.options["top_k"], 64)
            self.assertEqual(profile.options["repeat_penalty"], 1.1)

    def test_resident_chat_model_uses_ollama_numeric_sentinel(self):
        self.assertEqual(GEMMA_CHAT_PROFILE.keep_alive, -1)
        self.assertIsInstance(GEMMA_CHAT_PROFILE.keep_alive, int)


if __name__ == "__main__":
    unittest.main()
