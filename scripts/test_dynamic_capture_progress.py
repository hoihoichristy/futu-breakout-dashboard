#!/usr/bin/env python3
"""Offline regression tests for dynamic capture progress checkpoints."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_dynamic_capture_progress.py")


def payload(name, day="20261112"):
    return {
        "ret_code": 0,
        "data": {
            "kline_list": [{
                "date": day,
                "name": name,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "turnover": 1000.0,
            }]
        },
    }


class DynamicCaptureProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.universe = self.root / "universe.csv"
        with self.universe.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["code", "name"])
            writer.writeheader()
            writer.writerows([
                {"code": "US.AAA", "name": "Alpha Co"},
                {"code": "US.BBB", "name": "Beta Co"},
                {"code": "US.CCC", "name": "Gamma Co"},
            ])
        self.raw = self.root / "bars"
        self.raw.mkdir()
        self.manifest = self.raw / ".capture_manifest.json"
        self.log = self.root / "run.log"
        self.sources = {}

    def tearDown(self):
        self.tmp.cleanup()

    def add_capture(self, symbol, name):
        source = self.root / f"futu_quote_history_kline_{symbol.replace('.', '_')}.json"
        value = payload(name)
        source.write_text(json.dumps(value), encoding="utf-8")
        (self.raw / f"{symbol}.json").write_text(json.dumps(value), encoding="utf-8")
        self.sources[symbol] = str(source.resolve())
        self.manifest.write_text(json.dumps(self.sources), encoding="utf-8")

    def run_check(self):
        return subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--universe", str(self.universe),
                "--raw-dir", str(self.raw),
                "--started-epoch", "0",
                "--show-next", "2",
                "--log-path", str(self.log),
            ], text=True, capture_output=True, check=False,
        )

    def test_pending_checkpoint_lists_exact_next_symbols_and_logs(self):
        self.add_capture("US.AAA", "Alpha Co")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["universe_count"], 3)
        self.assertEqual(report["captured_count"], 1)
        self.assertEqual(report["pending_symbols"], ["US.BBB", "US.CCC"])
        self.assertEqual(report["next_symbols"], ["US.BBB", "US.CCC"])
        self.assertIn("CAPTURE_CHECKPOINT status=INCOMPLETE universe=3 captured=1 pending=2", self.log.read_text())

    def test_complete_manifest_reports_complete(self):
        self.add_capture("US.AAA", "Alpha Co")
        self.add_capture("US.BBB", "Beta Co")
        self.add_capture("US.CCC", "Gamma Co")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["next_symbols"], [])

    def test_identity_mismatch_fails_closed(self):
        self.add_capture("US.AAA", "Wrong Name")
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Security name mismatch", result.stderr)
        self.assertIn("CAPTURE_CHECKPOINT status=ERROR", self.log.read_text())

    def test_missing_captured_file_fails_closed(self):
        self.add_capture("US.AAA", "Alpha Co")
        (self.raw / "US.AAA.json").unlink()
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Captured bar JSON is missing", result.stderr)

    def test_duplicate_universe_code_fails_closed(self):
        with self.universe.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["code", "name"])
            writer.writerow({"code": "US.AAA", "name": "Duplicate"})
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate codes", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
