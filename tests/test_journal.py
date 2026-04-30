"""Tests for utils.journal: append-only JSONL coach memory."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from utils import journal


class TestJournalRecordAndRecall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "journal.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_round_trips_through_recall(self):
        journal.record(
            {"kind": "recommendation", "symbol": "AAPL", "rationale": "high IVR"},
            path=self.path,
        )
        entries = journal.recall(path=self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["symbol"], "AAPL")
        self.assertEqual(entries[0]["kind"], "recommendation")
        self.assertIn("ts", entries[0])

    def test_record_unknown_kind_coerced_to_note(self):
        journal.record({"kind": "wat", "rationale": "x"}, path=self.path)
        entries = journal.recall(path=self.path)
        self.assertEqual(entries[0]["kind"], "note")

    def test_recall_empty_when_path_missing(self):
        self.assertEqual(journal.recall(path=self.path / "nope"), [])

    def test_recall_filters_by_kind(self):
        journal.record({"kind": "note", "rationale": "x"}, path=self.path)
        journal.record({"kind": "recommendation", "rationale": "y"}, path=self.path)
        recs = journal.recall(kind="recommendation", path=self.path)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["rationale"], "y")

    def test_recall_filters_by_symbol_case_insensitive(self):
        journal.record({"kind": "note", "symbol": "aapl", "rationale": "x"}, path=self.path)
        journal.record({"kind": "note", "symbol": "MSFT", "rationale": "y"}, path=self.path)
        out = journal.recall(symbol="AAPL", path=self.path)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "aapl")

    def test_recall_days_filter_drops_old(self):
        old_ts = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
        journal.record({"kind": "note", "rationale": "old", "ts": old_ts}, path=self.path)
        journal.record({"kind": "note", "rationale": "new"}, path=self.path)
        recent = journal.recall(days=7, path=self.path)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["rationale"], "new")

    def test_recall_limit_caps_output(self):
        for i in range(5):
            journal.record({"kind": "note", "rationale": str(i)}, path=self.path)
        out = journal.recall(limit=3, path=self.path)
        self.assertEqual(len(out), 3)

    def test_recall_returns_newest_first(self):
        ts1 = "2026-01-01T10:00:00"
        ts2 = "2026-04-01T10:00:00"
        journal.record({"kind": "note", "rationale": "old", "ts": ts1}, path=self.path)
        journal.record({"kind": "note", "rationale": "new", "ts": ts2}, path=self.path)
        out = journal.recall(path=self.path)
        self.assertEqual(out[0]["rationale"], "new")
        self.assertEqual(out[1]["rationale"], "old")

    def test_malformed_line_is_skipped_not_raised(self):
        with self.path.open("w", encoding="utf-8") as f:
            f.write('{"kind":"note","rationale":"good"}\n')
            f.write("not json at all\n")
            f.write('{"kind":"note","rationale":"also good"}\n')
        out = journal.recall(path=self.path)
        rationales = sorted(e["rationale"] for e in out)
        self.assertEqual(rationales, ["also good", "good"])

    def test_stats_counts_by_kind(self):
        journal.record({"kind": "note", "rationale": "a"}, path=self.path)
        journal.record({"kind": "recommendation", "rationale": "b"}, path=self.path)
        journal.record({"kind": "note", "rationale": "c"}, path=self.path)
        s = journal.stats(path=self.path)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_kind"]["note"], 2)
        self.assertEqual(s["by_kind"]["recommendation"], 1)
        self.assertIsNotNone(s["last_ts"])


class TestJournalConcurrentAppend(unittest.TestCase):
    """Atomic-append safety: many simultaneous record() calls produce valid JSONL."""

    def test_concurrent_records_all_land_as_valid_lines(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            p = Path(tmp.name) / "journal.jsonl"

            async def driver():
                await asyncio.gather(*[
                    asyncio.to_thread(journal.record, {"kind": "note", "rationale": f"r{i}"}, path=p)
                    for i in range(50)
                ])

            asyncio.run(driver())

            with p.open("r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 50)
            for ln in lines:
                json.loads(ln)  # must parse
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
