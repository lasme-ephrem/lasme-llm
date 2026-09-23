"""Arrêt propre SQLite : le journal WAL doit être rapatrié, jamais supprimé."""

import tempfile
import unittest
from pathlib import Path

from core.memory.database import DatabaseManager


class DatabaseCheckpointTests(unittest.TestCase):
    def test_checkpoint_truncates_wal_and_data_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "checkpoint.db"
            manager = DatabaseManager(db_path)
            manager.set_setting("checkpoint_probe", "v1")

            result = manager.checkpoint()
            # wal_checkpoint renvoie (busy, log, checkpointed) : pas busy.
            self.assertIsNotNone(result)
            self.assertEqual(result[0], 0)
            self.assertEqual(result[2], result[1])

            # Relecture après « arrêt propre » : les écritures sont bien
            # rapatriées dans le fichier principal (leçon -wal).
            reopened = DatabaseManager(db_path)
            self.assertEqual(reopened.get_setting("checkpoint_probe"), "v1")


if __name__ == "__main__":
    unittest.main()
