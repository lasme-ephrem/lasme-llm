"""File de jobs et worker de fond (phases D2/E)."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.memory.jobs import JobStore


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_enqueue_claim_complete_roundtrip(self):
        job_id = self.store.enqueue("title", {"session_id": "s1", "model": "m"})
        self.assertEqual(self.store.pending_count(), 1)
        job = self.store.claim_next()
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["kind"], "title")
        self.assertEqual(job["payload"]["session_id"], "s1")
        # Un job running n'est plus réservable (aucun double traitement).
        self.assertIsNone(self.store.claim_next())
        self.store.complete(job_id)
        self.assertEqual(self.store.pending_count(), 0)

    def test_fail_keeps_the_error_and_the_job_visible(self):
        job_id = self.store.enqueue("session_memory", {"session_id": "s2"})
        job = self.store.claim_next()
        self.store.fail(job["id"], "boom")
        listed = self.store.list_jobs()
        self.assertEqual(listed[0]["status"], "error")
        self.assertEqual(listed[0]["error"], "boom")
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(job_id, job["id"])

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.enqueue("nimportequoi", {})

    def test_worker_process_one_executes_a_title_job(self):
        from chat.server.deps import deps
        from chat.worker.loop import process_one

        deps.bind(job_store=self.store)
        self.store.enqueue("title", {"session_id": "", "prompt": "", "model": ""})
        done = asyncio.run(process_one())
        self.assertTrue(done)
        # Le job est clos (échec ou succès) : jamais bloqué en running.
        self.assertEqual(self.store.pending_count(), 0)
        # Aucun second job : process_one ne travaille pas dans le vide.
        self.assertFalse(asyncio.run(process_one()))


if __name__ == "__main__":
    unittest.main()
