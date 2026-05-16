import json
import tempfile
import unittest
from pathlib import Path


class TestWriteOutputsNoDataJs(unittest.TestCase):
    def test_does_not_write_data_js(self):
        from pipeline.aggregate import write_outputs

        data = {
            "meta": {"updated_at": "2026-05-16T22:00:00"},
            "indices": {},
            "sectors": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "output": {
                    "json_path": f"{tmpdir}/output.json",
                    "cache_dir": f"{tmpdir}/cache",
                    "news_in_output": 5,
                }
            }
            write_outputs(data, cfg)

            self.assertTrue(
                Path(f"{tmpdir}/output.json").exists(),
                "output.json debe existir",
            )
            self.assertFalse(
                Path(f"{tmpdir}/data.js").exists(),
                "data.js NO debe existir",
            )

    def test_output_json_is_valid(self):
        from pipeline.aggregate import write_outputs

        data = {
            "meta": {"updated_at": "2026-05-16T22:00:00", "run_status": "success"},
            "indices": {"SPY": {"ytd": 5.2, "daily_change": 0.3}},
            "sectors": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "output": {
                    "json_path": f"{tmpdir}/output.json",
                    "cache_dir": f"{tmpdir}/cache",
                    "news_in_output": 5,
                }
            }
            write_outputs(data, cfg)

            with open(f"{tmpdir}/output.json", encoding="utf-8") as f:
                loaded = json.load(f)

            self.assertEqual(loaded["meta"]["updated_at"], "2026-05-16T22:00:00")
            self.assertEqual(loaded["indices"]["SPY"]["ytd"], 5.2)
