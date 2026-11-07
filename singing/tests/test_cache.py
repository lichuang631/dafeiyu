"""成品必须同曲同音色且完整；损坏或换声音后不能错误复用。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.wav"
        self.reference.write_bytes(b"reference-one")
        self.jobs = self.root / "jobs"
        self.job = self.jobs / ("a" * 32)
        self.job.mkdir(parents=True)
        (self.job / "request.json").write_text(json.dumps({"query": "叹云兮 鞠婧祎"}), encoding="utf-8")
        (self.job / "status.json").write_text(json.dumps({"state": "done", "parts": 1}), encoding="utf-8")
        (self.job / "part-0.mp3").write_bytes(b"x" * 20_000)
        cache.store_result(self.job, self.reference)

    def tearDown(self):
        self.temp.cleanup()

    def test_completed_result_is_reused_for_same_song_with_spacing_changes(self):
        self.assertEqual(cache.find_result("  叹云兮   鞠婧祎 ", self.reference, self.jobs), self.job.name)
        self.assertIsNone(cache.find_result("叹云兮 其他歌手", self.reference, self.jobs))

    def test_changing_voice_or_tampering_audio_invalidates_cache(self):
        self.reference.write_bytes(b"reference-two")
        self.assertIsNone(cache.find_result("叹云兮 鞠婧祎", self.reference, self.jobs))
        self.reference.write_bytes(b"reference-one")
        (self.job / "part-0.mp3").write_bytes(b"y" * 20_000)
        self.assertIsNone(cache.find_result("叹云兮 鞠婧祎", self.reference, self.jobs))

    def test_missing_part_or_incomplete_job_is_not_reused(self):
        (self.job / "part-0.mp3").unlink()
        self.assertIsNone(cache.find_result("叹云兮 鞠婧祎", self.reference, self.jobs))


if __name__ == "__main__":
    unittest.main()
