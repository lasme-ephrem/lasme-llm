"""Statistiques de génération agent.

Le tok/s affiché doit reposer sur la SOMME des temps de décodage réels des
appels modèle (hors exécution d'outils), pas sur la fenêtre temporelle du
seul flux de réponse finale — sinon un run à 970 tokens sur 0,23 s de
réponse finale affiche 4269 tok/s.
"""

import unittest

from chat.server.main import build_generation_stats
from core.agent.events import EventLog, TURN_END


def _turn(payload):
    log = EventLog()
    log.add(TURN_END, **payload)
    return log


class UsageTotalsTests(unittest.TestCase):
    def test_sums_tokens_and_decode_ns_across_turns(self):
        log = EventLog()
        log.add(TURN_END, turn=1, prompt_tokens=1500, output_tokens=400,
                eval_duration_ns=2_000_000_000,
                prompt_eval_duration_ns=600_000_000, done_reason="tool_calls")
        log.add(TURN_END, turn=2, prompt_tokens=1800, output_tokens=570,
                eval_duration_ns=3_500_000_000,
                prompt_eval_duration_ns=700_000_000, done_reason="stop")
        totals = log.usage_totals()
        self.assertEqual(totals["output_tokens"], 970)
        self.assertEqual(totals["prompt_tokens"], 3300)
        self.assertEqual(totals["eval_duration_ns"], 5_500_000_000)
        self.assertEqual(totals["prompt_eval_duration_ns"], 1_300_000_000)

    def test_missing_timing_keys_default_to_zero(self):
        log = _turn({"turn": 1, "prompt_tokens": 10, "output_tokens": 5,
                     "done_reason": "stop"})
        totals = log.usage_totals()
        self.assertEqual(totals["eval_duration_ns"], 0)
        self.assertEqual(totals["prompt_eval_duration_ns"], 0)


class AgentSpeedStatsTests(unittest.TestCase):
    def _chunk(self, eval_duration_ns):
        return {
            "eval_count": 970,
            "prompt_eval_count": 3300,
            "eval_duration": eval_duration_ns,
            "prompt_eval_duration": 1_300_000_000,
            "total_duration": 13_900_000_000,
            "done_reason": "stop",
        }

    def test_tokens_per_second_is_total_tokens_over_total_decode_time(self):
        stats = build_generation_stats(
            self._chunk(5_500_000_000),
            model="gemma-4-12b",
            started_at=__import__("time").monotonic() - 14.0,
            first_content_at=None,
        )
        # 970 tokens décodés en 5,5 s de génération modèle -> 176,4 tok/s,
        # même si le mur total est de ~14 s (outils compris).
        self.assertEqual(stats["tokens_per_second"], 176.4)
        self.assertEqual(stats["generation_seconds"], 5.5)
        self.assertGreaterEqual(stats["total_seconds"], 13.9)
        self.assertEqual(stats["output_tokens"], 970)

    def test_zero_decode_time_hides_speed_not_tokens(self):
        stats = build_generation_stats(
            self._chunk(0),
            model="gemma-4-12b",
            started_at=__import__("time").monotonic() - 2.0,
            first_content_at=None,
        )
        # Clé absente quand le décodage n'est pas mesurable : le frontend
        # masque la métrique au lieu d'afficher une vitesse fausse.
        self.assertNotIn("tokens_per_second", stats)
        self.assertEqual(stats["output_tokens"], 970)


if __name__ == "__main__":
    unittest.main()
