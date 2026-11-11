"""Unit tests for the pure parts of reel_autopost.poster. No network, no tokens."""

import calendar
import json
from pathlib import Path

import pytest

from reel_autopost import poster

# ---------- token cleaning ----------

@pytest.mark.parametrize("raw, expected", [
    ("abc123", "abc123"),
    ("  abc\n123 ", "abc123"),
    ("'abc123'", "abc123"),
    ('"abc123"', "abc123"),
    ("access_token=abc123", "abc123"),
    ("Token: abc123", "abc123"),
    ("", ""),
])
def test_clean_token(raw, expected):
    assert poster.clean_token(raw) == expected


# ---------- slot queues ----------

def test_slot_queue_manual_run_takes_anything():
    assert poster.in_slot_queue("001-asmr-clip.mp4", None, {"slot_queues": {"20": "asmr"}})


def test_slot_queue_dedicated_slot_only_takes_its_files():
    cfg = {"slot_queues": {"20": "asmr"}}
    assert poster.in_slot_queue("001-asmr-clip.mp4", 20, cfg)
    assert not poster.in_slot_queue("002-facts.mp4", 20, cfg)


def test_slot_queue_other_slots_skip_dedicated_files():
    cfg = {"slot_queues": {"20": "asmr"}}
    assert poster.in_slot_queue("002-facts.mp4", 17, cfg)
    assert not poster.in_slot_queue("001-asmr-clip.mp4", 17, cfg)


def test_slot_queue_no_config_accepts_all():
    assert poster.in_slot_queue("anything.mp4", 9, {})


# ---------- queue order ----------

def make_queue(tmp_path: Path, names):
    videos = tmp_path / "videos"
    videos.mkdir()
    for n in names:
        (videos / n).write_bytes(b"\x00")
    return videos


def test_next_video_in_name_order_skipping_posted(tmp_path):
    videos = make_queue(tmp_path, ["002-b.mp4", "001-a.mp4", "003-c.mov", "notes.txt"])
    state = {"posted": [{"file": "001-a.mp4"}]}
    assert poster.next_video(videos, state, {}).name == "002-b.mp4"


def test_next_video_returns_none_when_empty(tmp_path):
    assert poster.next_video(tmp_path / "missing", {"posted": []}, {}) is None


def test_next_video_respects_slot_queue(tmp_path):
    videos = make_queue(tmp_path, ["001-asmr.mp4", "002-facts.mp4"])
    cfg = {"slot_queues": {"20": "asmr"}}
    assert poster.next_video(videos, {"posted": []}, cfg, hour=17).name == "002-facts.mp4"
    assert poster.next_video(videos, {"posted": []}, cfg, hour=20).name == "001-asmr.mp4"


# ---------- captions and sidecars ----------

def test_caption_from_file_name(tmp_path):
    video = tmp_path / "how-tall-is-a-skyscraper.mp4"
    video.write_bytes(b"\x00")
    meta = poster.load_meta(video, {"default_hashtags": "#facts"})
    assert meta["caption"] == "how tall is a skyscraper\n\n#facts"


def test_caption_from_txt_sidecar(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    video.with_suffix(".txt").write_bytes(b"Hello\r\nworld\r\n")
    assert poster.load_meta(video, {})["caption"] == "Hello\nworld"


def test_json_sidecar_wins_and_keeps_extra_keys(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    video.with_suffix(".txt").write_text("ignored", encoding="utf-8")
    video.with_suffix(".json").write_text(json.dumps({"caption": "From json", "audio_volume": 25}))
    meta = poster.load_meta(video, {})
    assert meta == {"caption": "From json", "audio_volume": 25}


# ---------- sound choice ----------

ITEMS = [
    {"audio_id": "1", "title": "Spooky Halloween Beat", "display_artist": "A"},
    {"audio_id": "2", "title": "Summer Song", "display_artist": "B"},
    {"id": "3", "title": "Another One", "display_artist": "C"},
]


def test_choose_sound_skips_banned_words_and_recent():
    cfg = {"skip_sound_words": ["halloween"]}
    chosen = poster.choose_sound(ITEMS, cfg, recent_ids={"2"}, meta={})
    assert chosen["audio_id"] == "3"


def test_choose_sound_falls_back_when_all_recent():
    chosen = poster.choose_sound(ITEMS, {}, recent_ids={"1", "2", "3"}, meta={})
    assert chosen["audio_id"] == "1"


def test_choose_sound_honours_no_audio_and_explicit_id():
    assert poster.choose_sound(ITEMS, {}, set(), {"no_audio": True}) is None
    assert poster.choose_sound([], {}, set(), {"audio_id": 99})["audio_id"] == "99"


def test_choose_sound_raises_on_empty_list():
    with pytest.raises(RuntimeError):
        poster.choose_sound([], {}, set(), {})


# ---------- scheduling ----------

def test_scheduled_hour_parses_cron_and_manual():
    assert poster.scheduled_hour("23 17 * * *") == 17
    assert poster.scheduled_hour("") is None
    assert poster.scheduled_hour("bad") is None


def test_already_posted_for_slot_once_per_day():
    state = {"posted": [{"file": "a.mp4", "posted_at": "2026-11-02T17:25:00Z"}]}
    at_18 = calendar.timegm((2026, 11, 2, 18, 30, 0))
    assert poster.already_posted_for_slot(state, 17, {}, now=at_18)
    at_21 = calendar.timegm((2026, 11, 2, 21, 0, 0))
    assert not poster.already_posted_for_slot(state, 20, {}, now=at_21)


def test_already_posted_for_slot_late_run_crosses_midnight():
    now = calendar.timegm((2026, 11, 3, 1, 0, 0))  # 01:00 UTC next day
    state = {"posted": [{"file": "a.mp4", "posted_at": "2026-11-02T23:50:00Z"}]}
    assert poster.already_posted_for_slot(state, 20, {}, now=now)
