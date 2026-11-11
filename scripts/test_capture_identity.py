#!/usr/bin/env python3
"""Offline integration tests for Futu K-line returned-name validation."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("capture_latest_futu_result.py")


def make_payload(name, bars=2):
    rows = []
    for day in range(1, bars + 1):
        rows.append({
            "date": f"202611{day:02d}",
            "name": name,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "turnover": 1000.0,
        })
    return {"ret_code": 0, "data": {"kline_list": rows}}


class CaptureIdentityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.universe = self.root / "universe.csv"
        with self.universe.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["code", "name"])
            writer.writeheader()
            writer.writerow({"code": "US.CART", "name": "Maplebear"})
        self.source = self.root / "futu_quote_history_kline_fixture.json"
        self.raw_dir = self.root / "bars"
        self.manifest = self.raw_dir / ".capture_manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_capture(self, payload):
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--symbol", "US.CART",
                "--started-epoch", "0",
                "--raw-dir", str(self.raw_dir),
                "--screened-universe", str(self.universe),
                "--dynamic-screen", "--min-bars", "1",
                "--source-file", str(self.source),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_matching_returned_name_is_captured(self):
        result = self.run_capture(make_payload("Maplebear"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.raw_dir / "US.CART.json").is_file())
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["US.CART"], str(self.source.resolve()))

    def test_whitespace_and_case_normalization_is_allowed(self):
        result = self.run_capture(make_payload("  MAPLEBEAR  "))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("US.CART", json.loads(self.manifest.read_text(encoding="utf-8")))

    def test_mismatched_returned_name_is_rejected_without_writes(self):
        result = self.run_capture(make_payload("Sezzle"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Security name mismatch", result.stderr)
        self.assertFalse((self.raw_dir / "US.CART.json").exists())
        self.assertFalse(self.manifest.exists())

    def test_missing_returned_name_is_rejected_without_writes(self):
        payload = make_payload("Maplebear")
        for bar in payload["data"]["kline_list"]:
            del bar["name"]
        result = self.run_capture(payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Security name mismatch", result.stderr)
        self.assertFalse((self.raw_dir / "US.CART.json").exists())
        self.assertFalse(self.manifest.exists())

    def test_mixed_returned_names_are_rejected_without_writes(self):
        payload = make_payload("Maplebear")
        payload["data"]["kline_list"][1]["name"] = "Sezzle"
        result = self.run_capture(payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Security name mismatch", result.stderr)
        self.assertFalse((self.raw_dir / "US.CART.json").exists())
        self.assertFalse(self.manifest.exists())

    def test_exact_source_is_required_for_dynamic_capture(self):
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--symbol", "US.CART",
                "--started-epoch", "0",
                "--raw-dir", str(self.raw_dir),
                "--screened-universe", str(self.universe),
                "--dynamic-screen", "--min-bars", "1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires exact --source-file", result.stderr)
        self.assertFalse(self.manifest.exists())

    def test_ambiguous_or_duplicate_universe_identity_is_rejected(self):
        with self.universe.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["code", "name"])
            writer.writerow({"code": "US.CART", "name": "Another Name"})
        result = self.run_capture(make_payload("Maplebear"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected exactly one universe row", result.stderr)
        self.assertFalse((self.raw_dir / "US.CART.json").exists())
        self.assertFalse(self.manifest.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
