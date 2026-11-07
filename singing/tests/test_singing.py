"""核对点歌鉴权、幂等、并发限制、错误回收及音乐地址限制。"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

RUNTIME = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RUNTIME / "local-voice"), str(RUNTIME / "singing")]
import music
import singing_jobs as jobs
from gpu_lock import gpu_lock


class SingingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / ".venv/Scripts").mkdir(parents=True)
        (root / ".venv/Scripts/python.exe").touch()
        (root / "worker.py").touch()
        self.root = root
        self.patches = [patch.object(jobs, "ROOT", root), patch.object(jobs, "JOBS", root / "jobs"), patch.object(jobs, "processes", {})]
        for item in self.patches:
            item.start()

        def authenticate(header):
            if header != "Bearer unit-test":
                raise HTTPException(status_code=401)

        app = FastAPI()
        app.include_router(jobs.build_router(authenticate, {"reference_audio": "test-reference.wav"}))
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer unit-test"}
        self.body = {"query": "叹云兮 鞠婧祎", "request_id": "a" * 32}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def post(self, body=None):
        return self.client.post("/sing/jobs", json=body or self.body, headers=self.headers)

    def test_all_routes_require_authentication(self):
        self.assertEqual(self.client.post("/sing/jobs", json=self.body).status_code, 401)
        self.assertEqual(self.client.get("/sing/jobs/" + "a" * 32).status_code, 401)
        self.assertEqual(self.client.get("/sing/jobs/" + "a" * 32 + "/audio/0").status_code, 401)

    def test_download_url_is_not_accepted_as_query_or_job_path(self):
        self.assertEqual(self.post({**self.body, "query": "http://127.0.0.1/private"}).status_code, 422)
        self.assertEqual(self.post({**self.body, "request_id": "../other"}).status_code, 422)

    def test_same_request_is_idempotent_and_other_song_cannot_reuse_id(self):
        with patch.object(jobs.subprocess, "Popen", return_value=Mock(pid=123, poll=Mock(return_value=None))) as spawn:
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(self.post({**self.body, "query": "另一首歌"}).status_code, 409)
            self.assertEqual(spawn.call_count, 1)

    def test_busy_job_prevents_second_worker_and_stopped_job_becomes_error(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        with patch.object(jobs.subprocess, "Popen", return_value=process):
            self.post()
            self.assertEqual(self.post({**self.body, "request_id": "b" * 32}).status_code, 429)
            process.poll.return_value = 1
            status = self.client.get("/sing/jobs/" + "a" * 32, headers=self.headers).json()
            self.assertEqual(status["state"], "error")

    def test_finished_audio_has_bounded_index_and_file_size(self):
        folder = self.root / "jobs" / ("a" * 32)
        folder.mkdir(parents=True)
        (folder / "status.json").write_text(json.dumps({"state": "done", "parts": 1}))
        (folder / "part-0.mp3").write_bytes(b"ID3" + b"a" * 30)
        base = "/sing/jobs/" + "a" * 32 + "/audio/"
        self.assertEqual(self.client.get(base + "0", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(base + "1", headers=self.headers).status_code, 404)
        (folder / "part-0.mp3").write_bytes(b"a" * 2_000_001)
        self.assertEqual(self.client.get(base + "0", headers=self.headers).status_code, 404)

    def test_stalled_conversion_is_stopped_and_failure_is_saved(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        with patch.object(jobs.subprocess, "Popen", return_value=process):
            self.post()
        path = self.root / "jobs" / ("a" * 32) / "status.json"
        path.write_text(json.dumps({"state": "converting", "seconds": 60, "started_at": time.time() - 130, "updated_at": time.time() - 125}), encoding="utf-8")
        with patch.object(jobs.subprocess, "run") as kill:
            result = self.client.get("/sing/jobs/" + "a" * 32, headers=self.headers).json()
            self.assertEqual(result["state"], "error")
            self.assertIn("超时", result["message"])
            self.assertIn("123", kill.call_args.args[0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "error")

    def test_music_hosts_reject_private_paths_credentials_and_similar_domains(self):
        for url in ("http://127.0.0.1/a", "http://qq.com.evil.test/a", "file:///C:/data", "https://user:pass@qq.com/a", "https://qq.com:3000/a"):
            self.assertFalse(music.allowed_audio_url(url), url)
        self.assertTrue(music.allowed_audio_url("https://isure.stream.qqmusic.qq.com/song.mp3"))

    def test_explicit_artist_mismatch_does_not_select_another_singer(self):
        response = Mock()
        response.json.return_value = {"data": {"song": {"list": [{"songname": "叹云兮", "singer": [{"name": "另一位歌手"}], "songmid": "test"}]}}}
        with patch.object(music.requests, "get", return_value=response), self.assertRaises(music.MusicUnavailable):
            music.search_song("叹云兮 鞠婧祎")

    def test_gpu_lock_times_out_and_is_released(self):
        path = self.root / "gpu-test.lock"
        with gpu_lock(timeout=0.1, lock_path=path), self.assertRaises(TimeoutError):
            with gpu_lock(timeout=0.1, lock_path=path):
                self.fail("不应同时进入同一个显卡锁")
        with gpu_lock(timeout=0.1, lock_path=path):
            pass


if __name__ == "__main__":
    unittest.main()
