"""Tests for the smart-home device-state reconstruction (backend/devices.py).

The reconstruction replays recorded tool-call arguments into a device state.
These tests pin the mapping from tool args -> state so a refactor can't change
what the smart-controls panel shows.
"""

from pathlib import Path

from backend import devices, ingest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _span(tool, args, at=1000.0):
    return {"tool": tool, "arguments": args, "at": at, "duration_s": 0.02, "error": None}


def test_control_lights_on_off():
    spans = [
        _span("control_lights", {"action": "on", "value": ""}, 1),
        _span("control_lights", {"action": "off", "value": ""}, 2),
    ]
    r = devices.reconstruct(spans)
    assert r["args_recorded"] is True
    assert r["final"]["lights"]["power"] is False  # last call turned it off
    assert r["events"][0]["change"] == "light on"
    assert r["events"][1]["change"] == "light off"


def test_control_lights_brightness_and_color():
    spans = [
        _span("control_lights", {"action": "brightness", "value": "60"}, 1),
        _span("control_lights", {"action": "color", "value": "Blue"}, 2),
    ]
    r = devices.reconstruct(spans)
    lights = r["final"]["lights"]
    assert lights["power"] is True
    assert lights["brightness"] == "60"
    assert lights["color"] == "Blue"


def test_set_thermostat():
    r = devices.reconstruct([_span("set_thermostat", {"degrees": 24}, 5)])
    assert r["final"]["thermostat"]["degrees"] == 24
    assert r["final"]["thermostat"]["set_at"] == 5
    assert r["events"][0]["change"] == "set to 24°C"


def test_media_and_reminders_and_timer():
    spans = [
        _span("play_music", {"query": "chill jazz"}, 1),
        _span("add_reminder", {"text": "drink water"}, 2),
        _span("set_timer", {"duration_s": 30}, 3),
    ]
    r = devices.reconstruct(spans)
    assert r["final"]["media"]["status"] == "playing"
    assert r["final"]["media"]["title"] == "chill jazz"
    assert r["final"]["reminders"] == [{"text": "drink water", "created_ms": 2000.0}]
    # timer ends_at = at + duration
    assert r["final"]["timers"][0]["label"] == "30s"
    assert r["final"]["timers"][0]["ends_at"] == 33


def test_playback_control_maps_status():
    spans = [
        _span("play_music", {"query": "x"}, 1),
        _span("playback_control", {"action": "pause"}, 2),
    ]
    r = devices.reconstruct(spans)
    assert r["final"]["media"]["status"] == "paused"


def test_recorded_media_result_overrides_replayed_volume_and_title():
    play = _span("play_music", {"query": "local files"}, 1)
    play["result"] = {"ok": True, "media": {"mode": "music", "title": "Track A",
                                            "status": "playing", "volume": 1}}
    change = _span("playback_control", {"action": "volume_up"}, 2)
    change["result"] = {"ok": True, "media": {"mode": "music", "title": "Track B",
                                              "status": "playing", "volume": 4}}
    r = devices.reconstruct([play, change])
    assert r["results_recorded"] is True
    assert r["final"]["media"]["title"] == "Track B"
    assert r["final"]["media"]["volume"] == 4


def test_place_call():
    r = devices.reconstruct([_span("place_call", {"to": "Mom"}, 7)])
    assert r["final"]["call"]["status"] == "calling"
    assert r["final"]["call"]["to"] == "Mom"


def test_no_args_means_not_recorded():
    r = devices.reconstruct([
        {"tool": "control_lights", "arguments": None, "at": 1, "duration_s": 0.02, "error": None},
    ])
    assert r["args_recorded"] is False
    # state unchanged from initial defaults
    assert r["final"]["lights"]["power"] is False


def test_committed_sample_runs_have_no_args():
    # The committed diagnostics predate argument logging.
    for run in ingest.list_runs(str(DATA_DIR)):
        d = run.detail()["devices"]
        assert d["args_recorded"] is False
        assert d["reconstructed"] is True
