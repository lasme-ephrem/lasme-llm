import unittest

from core.inference.profiles import (
    FAST_MODEL,
    GEMMA4_CHAT_PROFILE,
    GEMMA4_FAST_PROFILE,
    GEMMA4_MINIMAL_PROFILE,
    MINIMAL_MODEL,
    QUALITY_MODEL,
    get_model_profile,
    resolve_runtime_profile,
)


class ModelProfileTests(unittest.TestCase):
    def test_selects_chat_profile_with_or_without_latest_tag(self):
        self.assertIs(get_model_profile("gemma-4-chat"), GEMMA4_CHAT_PROFILE)
        self.assertIs(
            get_model_profile("gemma-4-chat:latest"), GEMMA4_CHAT_PROFILE
        )

    def test_legacy_runtime_models_fall_back_to_quality(self):
        # muse-glimmer, fable and qwen-vision were heterogeneous Ollama
        # models; the v2 platform serves one Gemma 4 family and maps every
        # legacy chat/agent alias onto the quality profile.
        for legacy in (
            "muse-glimmer:30b-q4_K_M-dflash",
            "gemma-4-fable",
            "lasme-qwen-vision",
        ):
            self.assertIs(get_model_profile(legacy), GEMMA4_CHAT_PROFILE)
            self.assertEqual(
                resolve_runtime_profile(legacy).id, QUALITY_MODEL, legacy
            )

    def test_selects_fast_and_minimal_profiles(self):
        fast = get_model_profile("lasme-smol-fast")
        minimal = get_model_profile(MINIMAL_MODEL)
        self.assertIs(fast, GEMMA4_FAST_PROFILE)
        self.assertIs(minimal, GEMMA4_MINIMAL_PROFILE)
        self.assertLess(fast.num_ctx, GEMMA4_CHAT_PROFILE.num_ctx)
        self.assertFalse(fast.think)
        self.assertFalse(minimal.think)
        self.assertTrue(fast.system_addendum)

    def test_quality_profile_uses_measured_phase0_settings(self):
        # Context 128K and history budget sized from Phase 0 measurements
        # Measured on the reference 16 GiB GPU: 128K fits with MTP n=4.
        self.assertEqual(GEMMA4_CHAT_PROFILE.num_ctx, 131_072)
        self.assertEqual(GEMMA4_CHAT_PROFILE.num_predict, 8_192)
        self.assertEqual(GEMMA4_CHAT_PROFILE.history_tokens, 60_000)
        self.assertTrue(GEMMA4_CHAT_PROFILE.think)
        self.assertEqual(GEMMA4_CHAT_PROFILE.options["top_p"], 0.95)
        self.assertEqual(GEMMA4_CHAT_PROFILE.options["top_k"], 64)

    def test_profiles_carry_runtime_ids(self):
        self.assertEqual(GEMMA4_CHAT_PROFILE.runtime_id, QUALITY_MODEL)
        self.assertEqual(GEMMA4_FAST_PROFILE.runtime_id, FAST_MODEL)
        self.assertEqual(GEMMA4_MINIMAL_PROFILE.runtime_id, MINIMAL_MODEL)


if __name__ == "__main__":
    unittest.main()
