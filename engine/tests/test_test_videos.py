"""Videos of the tests a run's conclusions rest on (issue #286): which tests are cited,
how the runner hands them to the adapter, and how a kept video shows in the report.
No browser and no model calls; the recording itself is checked live."""

from pathlib import Path

from engine.adapters.web_gui import adapter as adp
from engine.adapters.web_gui import session as live_session
from engine.runner import cited_tests, keep_test_media


def _output():
    return {
        "checkpoints": [
            {"hypothesis": {"observations": [{"tests": [2, 3]}]},
             "debrief": [{"answer": {"tests": [5]}}, {"answer": {"stance": "concede", "tests": []}}]},
            {"hypothesis": {"observations": []}},
        ],
        "observations": [{"tests": [3, 7]}],
        "replays": [{"tests": [{"test": 3, "replay": 20}]}],
        "casting_log": [{"test_number": n} for n in range(1, 9)],
    }


def test_the_cited_tests_are_the_observations_and_the_debrief_answers():
    assert cited_tests(_output()) == {2, 3, 5, 7}
    assert cited_tests({}) == set()


def test_each_kept_video_goes_on_its_tests_entry(tmp_path):
    asked = []
    def save(numbers, out_dir):
        asked.append((numbers, out_dir))
        return {3: "videos/test_3.webm", 7: "videos/test_7.webm"}
    output = _output()
    keep_test_media(type("A", (), {"save_test_media": staticmethod(save)})(), output, tmp_path)
    assert asked == [({2, 3, 5, 7}, tmp_path)]
    assert {e["test_number"]: e.get("video") for e in output["casting_log"] if "video" in e} == {
        3: "videos/test_3.webm", 7: "videos/test_7.webm"}


def test_a_video_that_fails_to_save_doesnt_fail_the_run(tmp_path):
    def save(numbers, out_dir):
        raise OSError("disk full")
    output = _output()
    keep_test_media(type("A", (), {"save_test_media": staticmethod(save)})(), output, tmp_path)
    assert not any("video" in e for e in output["casting_log"])


def test_the_report_shows_a_kept_video_in_its_test():
    entry = {"test_number": 3, "request": {"state": "st01", "control": "button:A"}, "predicted_outcome": "p",
             "predicted_screen": "same_screen", "actual_screen": "same_screen", "prediction_matched": True,
             "result": {"verdict": "sent", "reached_target_state": True}, "video": "videos/test_3.webm"}
    html = adp.render_test_entry(entry)
    assert '<video controls preload="none" width="640" src="videos/test_3.webm">' in html
    assert "<video" not in adp.render_test_entry({**entry, "video": None})


def test_no_session_means_no_videos(monkeypatch, tmp_path):
    monkeypatch.setattr(live_session, "_SESSION", None)
    assert adp.save_test_media({1}, tmp_path) == {}


def test_videos_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("WEB_GUI_VIDEO", "off")
    assert not live_session.video_on()
    monkeypatch.delenv("WEB_GUI_VIDEO")
    assert live_session.video_on()


class _Video:
    def __init__(self):
        self.saved_to = None

    def save_as(self, path):
        self.saved_to = Path(path)
        Path(path).write_bytes(b"webm")


def test_the_session_keeps_only_the_videos_asked_for(tmp_path, monkeypatch):
    session = live_session.Session.__new__(live_session.Session)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    session._video_dir = str(scratch)
    opened = []
    monkeypatch.setattr(session, "_open_fresh_page", lambda: opened.append(session._video_dir), raising=False)
    session._videos = {1: _Video(), 2: _Video()}
    saved = session.save_videos({2, 9}, tmp_path / "videos")
    assert saved == {2: "test_2.webm"}
    assert (tmp_path / "videos" / "test_2.webm").exists() and not (tmp_path / "videos" / "test_1.webm").exists()
    # Recording stops before the videos are saved, so the last one is complete.
    assert opened == [None]
    # The videos nobody asked for go with the scratch folder.
    assert not scratch.exists()
    assert session.save_videos({2}, tmp_path / "again") == {}
