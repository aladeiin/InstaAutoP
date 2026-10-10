import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autopilot import instagram, media, render, scriptgen, tts
from autopilot.config import load_config
from autopilot.state import State


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def make_script(words_per_scene=12, scenes=7, **over):
    sc = [{"narration": " ".join(["word"] * words_per_scene) + ".", "visual": "city street"}
          for _ in range(scenes)]
    sc[0]["narration"] = "Short hook line that grabs attention fast."
    script = {"topic": "t", "title": "A title", "scenes": sc, "caption": "Cap?",
              "hashtags": ["#a", "#b", "#c"], "facts": ["A fact."]}
    script.update(over)
    return script


# ---- state -----------------------------------------------------------------
def test_state_rotation_and_dedupe(tmp_path):
    s = State(tmp_path / "state.json")
    rot = ["finance", "history"]
    assert s.next_niche(rot) == "finance"
    s.record("2026-10-11", "finance", "Compounding", "1", True)
    assert s.next_niche(rot) == "history"
    assert s.posted_today("2026-10-11") and not s.posted_today("2026-10-12")
    s.record("2026-10-12", "history", "Fall of X", "2", True)
    assert s.next_niche(rot) == "finance"
    assert State(tmp_path / "state.json").recent_titles("finance") == ["Compounding"]


# ---- captions --------------------------------------------------------------
def test_chunk_words_groups_and_holds():
    words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3}
             for i, t in enumerate("one two three four five six seven".split())]
    chunks = tts.chunk_words(words, per_chunk=3)
    assert [c[0] for c in chunks] == ["one two three", "four five six", "seven"]
    assert chunks[0][2] >= chunks[1][1]  # held until the next caption starts


# ---- script validation -----------------------------------------------------
def test_validate_accepts_good_script(cfg):
    scriptgen.validate_script(make_script(), cfg)


@pytest.mark.parametrize("script,msg", [
    (make_script(scenes=3), "scenes"),
    (make_script(words_per_scene=2), "words"),
    (make_script(words_per_scene=40), "words"),
    (make_script(hashtags=["#a"]), "hashtags"),
    (make_script(facts=[]), "facts"),
])
def test_validate_rejects_bad_script(cfg, script, msg):
    with pytest.raises(ValueError, match=msg):
        scriptgen.validate_script(script, cfg)


def test_finalize_adds_footer_and_dedupes_tags(cfg):
    out = scriptgen.finalize(make_script(hashtags=["#MoneyTips", "personalfinance", "#x"]),
                             cfg["niches"]["finance"])
    cap = out["full_caption"]
    assert "not financial advice" in cap
    assert cap.lower().count("#moneytips") == 1


# ---- generation loop with a fake Claude ------------------------------------
class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        text = self.replies.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_generate_retries_after_factcheck_failure(cfg):
    good = json.dumps(make_script())
    client = FakeClient([
        good, json.dumps({"verdict": "fail", "issues": ["date is wrong"]}),
        good, json.dumps({"verdict": "pass", "issues": []}),
    ])
    out = scriptgen.generate(client, cfg, "history", [], [])
    assert "full_caption" in out and not client.replies


def test_generate_gives_up_without_posting(cfg):
    good = json.dumps(make_script())
    fail = json.dumps({"verdict": "fail", "issues": ["bad"]})
    client = FakeClient([good, fail] * cfg["claude"]["max_attempts"])
    with pytest.raises(scriptgen.ScriptRejected):
        scriptgen.generate(client, cfg, "finance", [], [])


def test_generate_handles_fenced_json_and_format_errors(cfg):
    good = "```json\n" + json.dumps(make_script()) + "\n```"
    client = FakeClient(["not json at all", good,
                         json.dumps({"verdict": "pass", "issues": []})])
    assert scriptgen.generate(client, cfg, "history", [], [])["title"] == "A title"


# ---- instagram flow with mocked HTTP ---------------------------------------
class FakeResp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def test_publish_reel_flow(cfg, monkeypatch):
    calls = []
    statuses = iter([{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}])

    def fake_request(method, url, params=None, data=None, timeout=None):
        calls.append((method, url))
        if url.endswith("/media"):
            assert data["media_type"] == "REELS" and data["video_url"].startswith("https://")
            return FakeResp({"id": "C1"})
        if url.endswith("/C1"):
            return FakeResp(next(statuses))
        if url.endswith("/media_publish"):
            assert data["creation_id"] == "C1"
            return FakeResp({"id": "M1"})
        raise AssertionError(url)

    monkeypatch.setattr(instagram.requests, "request", fake_request)
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)
    cl = instagram.InstagramClient(cfg, user_id="U", token="T")
    assert cl.publish_reel("https://x/y.mp4", "cap") == "M1"
    assert [m for m, _ in calls] == ["POST", "GET", "GET", "POST"]


def test_publish_reel_reports_processing_error(cfg, monkeypatch):
    def fake_request(method, url, params=None, data=None, timeout=None):
        if url.endswith("/media"):
            return FakeResp({"id": "C1"})
        return FakeResp({"status_code": "ERROR", "status": "bad codec"})

    monkeypatch.setattr(instagram.requests, "request", fake_request)
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)
    with pytest.raises(instagram.InstagramError, match="bad codec"):
        instagram.InstagramClient(cfg, user_id="U", token="T").publish_reel("https://x", "c")


def test_api_error_does_not_leak_token(cfg, monkeypatch):
    monkeypatch.setattr(instagram.requests, "request", lambda *a, **k: FakeResp(
        {"error": {"code": 190, "message": "Token expired"}}, 400))
    with pytest.raises(instagram.InstagramError) as e:
        instagram.InstagramClient(cfg, user_id="U", token="SECRET").check()
    assert "SECRET" not in str(e.value) and "190" in str(e.value)


# ---- real ffmpeg render with synthetic inputs ------------------------------
def _tone(path, seconds):
    media.run_ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                      "-c:a", "libmp3lame", str(path)])


def _fake_footage(path):
    # landscape clip to prove the crop-to-portrait step works
    media.run_ffmpeg(["-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=2",
                      "-pix_fmt", "yuv420p", str(path)])


def test_render_scenes_and_concat(cfg, tmp_path):
    audio1, audio2, clip = tmp_path / "a1.mp3", tmp_path / "a2.mp3", tmp_path / "f.mp4"
    _tone(audio1, 1.5)
    _tone(audio2, 1.0)
    _fake_footage(clip)
    caps = [("Hello there", 0.0, 0.7), ("big world", 0.7, 1.5)]
    s1 = render.render_scene(clip, audio1, 1.8, caps, tmp_path, 0, cfg)       # footage, looped
    s2 = render.render_scene(None, audio2, 1.3, caps[:1], tmp_path, 1, cfg)   # plain background
    final = render.concat_scenes([s1, s2], tmp_path / "video.mp4")

    assert abs(media.probe_duration(final) - 3.1) < 0.3
    info = subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-i", str(final)],
                          capture_output=True, text=True).stderr
    assert "1080x1920" in info and "h264" in info and "aac" in info
