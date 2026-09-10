"""The Clash Royale adapter, tested without a client and without a Win32 API.

Two different things are checked here and they carry very different weight.

The safety tests are the important half, and what makes them worth writing is that
every one of them fails *silently* in production. An empty denylist forbids nothing
and reports every action as allowed; a schema that accepts a coordinate accepts it
without complaint; a guard refusal that propagates as PermissionError looks like a
crashed run rather than a safety system working. None of these announces itself, so
each one gets a test that asserts the refusal rather than the success.

The session tests are the other half: screen identification, the board tripwire,
and recovery after landing somewhere new. These use a fake controller, because the
thing under test is the bookkeeping around a frame comparison and not the frame
comparison itself - which is `battle.fraction_changed`, already tested against real
captures in experiments/android-bot/test_battle.py.

Where the real geometry matters - does the shipped denylist actually cover the
shipped action points - a fake target would be testing the fake. Those tests import
the real `Target` and skip where it cannot be imported, which is honest about the
fact that this adapter only exists on the machine the client runs on.
"""

import pytest

from engine.adapter import validate_adapter
from engine.adapters.clash_royale import adapter as cr
from engine.adapters.clash_royale import reference
from engine.adapters.clash_royale import session as cr_session
from engine.adapters.clash_royale.actions import (
    BY_NAME,
    CASTING_ACTIONS,
    CATALOGUE,
    GUARD_PROBES,
    RECOVERY,
    Unsafe,
    preflight,
    vet,
)


class FakeTarget:
    """Just enough of `Target` to answer `forbids`, with the real containment test.

    The arithmetic is copied from `Target.forbids` rather than abstracted out of it,
    which is a duplication taken on purpose: these tests are about what `preflight`
    does with a guard's answers, and importing the real Target here would make every
    one of them require Win32 for no gain. The tests that genuinely depend on the
    real geometry are at the bottom of this file and import the real thing.
    """

    name = "Clash Royale"
    cell_delta = 10

    def __init__(self, denylist):
        self.denylist = denylist

    def forbids(self, fx, fy):
        for entry in self.denylist:
            x, y, w, h = entry["box"]
            if x <= fx <= x + w and y <= fy <= y + h:
                return entry.get("why", "denylisted")
        return None


def _guarding_target(extra=()):
    """A target that refuses every guard probe and nothing else.

    Built from GUARD_PROBES rather than from the shipped denylist so that these
    tests keep testing preflight's logic if the shipped boxes are ever re-measured.
    Each box is a hair around one probe point.
    """
    boxes = [{"box": (at[0] - 0.01, at[1] - 0.01, 0.02, 0.02), "why": f"guards {what}"}
             for what, at in GUARD_PROBES]
    return FakeTarget(boxes + list(extra))


# --- safety: preflight is the layer that catches the silent failures ----------

def test_preflight_refuses_an_empty_denylist():
    """The failure that looks exactly like success. `Target.denylist` comes from
    `DENYLISTS.get(_squash(name), [])`, so a game name that squashes to anything
    but "clashroyale" produces a target that forbids nothing and cheerfully
    reports every action as allowed."""
    with pytest.raises(Unsafe) as raised:
        preflight(FakeTarget([]))
    assert "empty coordinate denylist" in str(raised.value)


def test_preflight_refuses_a_denylist_that_no_longer_covers_the_controls():
    """A denylist that loaded but whose boxes have drifted. This is the realistic
    decay mode: the client is updated, the shop tab moves, and the box that used
    to cover it now covers whatever moved into its place."""
    drifted = FakeTarget([{"box": (0.0, 0.0, 0.01, 0.01), "why": "somewhere harmless"}])
    with pytest.raises(Unsafe) as raised:
        preflight(drifted)
    message = str(raised.value)
    assert "does not refuse" in message
    # Every unguarded control has to be named, not just counted: the operator's next
    # action is to re-measure a specific box.
    for what, _ in GUARD_PROBES:
        assert what in message


def test_preflight_refuses_an_action_that_is_itself_denylisted():
    """Not a safety hole - `Controller.click` would refuse it anyway - but it means
    an action point has drifted onto something forbidden, which is much more likely
    to mean the coordinate is wrong than that the Driver got lucky."""
    swallowed = {"box": (0.0, 0.0, 1.0, 1.0), "why": "everything, for the sake of argument"}
    with pytest.raises(Unsafe) as raised:
        preflight(_guarding_target(extra=[swallowed]))
    message = str(raised.value)
    assert "themselves denylisted" in message
    assert RECOVERY in message


def test_preflight_reports_every_probe_and_every_action_when_it_passes():
    """The report is not decoration: it is what the operator reads to approve a run,
    and their standing rule is that the boxes and what they block are shown. A
    preflight that passed quietly would satisfy the guard and defeat the review."""
    report = preflight(_guarding_target())
    for what, _ in GUARD_PROBES:
        assert what in report
        assert "refused" in report
    for action in CATALOGUE:
        assert action.name in report
        assert action.reversible in report
    assert "no drags" in report


def test_no_catalogue_action_sits_inside_the_shipped_denylist():
    """The real geometry, against the real guard. Everything above uses a fake
    target, so this is the one test that can catch a shipped action point that has
    drifted onto the shop tab."""
    target = _shipped_target()
    forbidden = [(a.name, why) for a, why in vet(target) if why]
    assert not forbidden, f"shipped action points inside a denylisted box: {forbidden}"


def test_the_shipped_denylist_refuses_every_guard_probe():
    """The other half of the same check, from the other direction: the boxes as
    shipped actually cover the controls they were written for."""
    target = _shipped_target()
    unguarded = [what for what, at in GUARD_PROBES if target.forbids(*at) is None]
    assert not unguarded, f"the shipped denylist does not cover: {unguarded}"


def _shipped_target():
    """The real `Target` with the real DENYLISTS entry, or skip.

    Skipped rather than faked where Win32 is absent, because a fake here would be
    testing the fake: the whole value of the two tests above is that they use the
    coordinates and the containment test that will actually run.
    """
    controller = pytest.importorskip(
        "controller", reason="the Win32 harness is only importable on the machine the client runs on")
    target_module = pytest.importorskip("target")
    return controller.Target(
        name="Clash Royale", window_title="Clash Royale", exe="",
        denylist=target_module.DENYLISTS["clashroyale"],
    )


# --- safety: the schema cannot express an unvetted tap -----------------------

def _walk(node):
    """Every dict in a nested JSON-schema structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_the_casting_schema_has_no_numeric_field_anywhere():
    """The first safety layer, asserted rather than assumed.

    The argument that an invented coordinate cannot be sent rests entirely on the
    Driver having no numeric field to put one in - not on the prompt asking it not
    to. So the property worth testing is not "the action field is an enum" but "no
    field in this whole schema accepts a number", which is what would still hold
    after someone adds a well-meaning `hold_ms` or `repeat` next year.
    """
    numeric = [node for node in _walk(cr.CASTING_TOOL["input_schema"])
               if node.get("type") in ("number", "integer")]
    assert not numeric, (
        f"the casting schema accepts {len(numeric)} numeric field(s). A number in this schema is "
        f"a number a model wrote being sent to a live account: {numeric}"
    )


def test_the_action_field_is_an_enum_of_exactly_the_catalogue():
    """Both directions. A catalogue entry missing from the enum is an action the
    Driver can never use; an enum entry missing from the catalogue is a name the
    Driver can send that nothing can execute."""
    action_schema = cr.CASTING_TOOL["input_schema"]["properties"]["candidate_tests"]["items"]["properties"]["action"]
    assert set(action_schema["enum"]) == set(BY_NAME)
    assert set(CASTING_ACTIONS) == set(BY_NAME)


def test_validation_rejects_an_action_outside_the_catalogue():
    """The schema is a request; this is the enforcement. A model can return a
    tool-call argument outside a declared enum, and the whole safety argument is
    that such a name has no vetted coordinate behind it - so it must be rejected
    and resubmitted, not sent."""
    errors = cr.validate_casting_response({
        "give_up": False, "reasoning": "x",
        "candidate_tests": [{"linked_hypothesis": "", "action": "open_shop",
                             "predicted_screen": "new_screen", "predicted_outcome": "y"}],
    })
    assert any("open_shop" in e for e in errors)


def test_validation_rejects_a_prediction_outside_the_three():
    errors = cr.validate_casting_response({
        "give_up": False, "reasoning": "x",
        "candidate_tests": [{"linked_hypothesis": "", "action": RECOVERY,
                             "predicted_screen": "the shop opens", "predicted_outcome": "y"}],
    })
    assert any("predicted_screen" in e for e in errors)


def test_a_well_formed_round_validates():
    """The negative tests above would all pass against a validator that rejected
    everything."""
    assert cr.validate_casting_response({
        "give_up": False, "reasoning": "x",
        "candidate_tests": [{"linked_hypothesis": "a theory", "action": RECOVERY,
                             "predicted_screen": "same_screen", "predicted_outcome": "y"}],
    }) == []


def test_the_adapter_validates_as_a_non_http_sut():
    """It supplies both reach hooks and no base_url, which is the shape the engine
    only started accepting for this adapter's sake."""
    validate_adapter(cr.ADAPTER)
    assert cr.ADAPTER.base_url == ""


def test_the_driver_is_told_what_is_off_limits_and_how_to_leave():
    """The prompt is not the safety layer, but a Driver that does not know a dialog
    is a thing to leave will spend tests trying to explore one."""
    briefing = cr.API_SCHEMA_DOC + cr.SAFETY_NOTE
    assert "dismiss" in briefing and RECOVERY in briefing
    assert "aborts" in briefing


# --- the session: screens, the tripwire, and getting back --------------------

class FakeController:
    """A window that shows whatever the test says, and records every tap.

    `clicks` is the assertion surface for the tests that care about what was sent:
    a refusal that quietly clicked anyway, or a recovery that never happened, both
    show up as the wrong list here rather than as a passing test.
    """

    def __init__(self, frames, pink=0.0, denylist=()):
        self.target = FakeTarget(list(denylist))
        self.frames = list(frames)
        self.pink = pink
        self.clicks: list[tuple[float, float]] = []
        self.settles = 0

    def grab(self, cols, rows, region=(0.0, 0.0, 1.0, 1.0), verify=True):
        # Held at the last frame rather than exhausted, so a test only has to
        # script the frames it is actually making a claim about.
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def capture(self, region=(0.0, 0.0, 1.0, 1.0), longest=1400):
        return b"", 0, 0

    def click(self, fx, fy, **kwargs):
        why = self.target.forbids(fx, fy)
        if why:
            raise PermissionError(f"({fx:.3f}, {fy:.3f}) is denylisted: {why}")
        self.clicks.append((fx, fy))

    def wait_stable(self, **kwargs):
        self.settles += 1
        return 0.5


class FakeBattle:
    """`battle`'s two functions, as this adapter uses them.

    `fraction_changed` compares whole frames rather than cells, which is coarser
    than the real one and enough for what it is used for here: the idle-drift check,
    which only ever asks whether two frames a second apart are the same.
    """

    def __init__(self, controller):
        self.controller = controller

    def elixir_showing(self, _controller):
        return self.controller.pink

    @staticmethod
    def fraction_changed(before, after, cells, cell_delta):
        return 0.0 if before == after else 1.0


class FakeRecon:
    """`recon`'s comparison functions, reimplemented rather than faked.

    The two that matter - `diff_cells` and `agreement` - are copies of the real
    ones, not stubs, because a stub here would test the stub: the whole question
    these session tests ask is whether the right frame is matched against the right
    stored fingerprint under a real threshold. The copy is kept honest by
    `test_the_fake_recon_agrees_with_the_real_one`, which runs where `recon` imports.
    """

    MIN_STABLE_CELLS = 40
    NCELLS = 576

    @staticmethod
    def fingerprint(controller):
        raw = controller.grab(32, 18)
        out = bytearray()
        for i in range(0, len(raw), 4):
            out += raw[i:i + 3]
        return bytes(out)

    @staticmethod
    def diff_cells(a, b, delta):
        return {i // 3 for i in range(0, min(len(a), len(b)), 3)
                if (abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1])
                    + abs(a[i + 2] - b[i + 2])) // 3 > delta}

    @classmethod
    def agreement(cls, fp, rep, volatile, delta):
        differing = cls.diff_cells(fp, rep, delta)
        stable_count = cls.NCELLS - len(volatile)
        if stable_count <= 0:
            return 0.0, 0, differing
        return 1.0 - len(differing - volatile) / stable_count, stable_count, differing


def frame(fill: int) -> bytes:
    """One full-size BGRA grab of a single flat colour.

    Full size on purpose: `_identify` refuses a frame that is not 576 cells, so a
    short fake frame would test the refusal instead of the comparison. Flat colours
    because two of them differ in every cell, which is what makes "same screen" and
    "different screen" unambiguous in a test that is not about the frame comparison.
    """
    return bytes((fill, fill, fill, 255)) * FakeRecon.NCELLS


def fingerprint_of(fill: int) -> bytes:
    """The same frame in stored form: 576 cells of BGR, alpha stripped."""
    return bytes((fill, fill, fill)) * FakeRecon.NCELLS


def carried(screen_id: str, fill: int, verdict: str = "ok", name: str | None = None):
    """One `Candidate` standing in for a carried screen, at a colour a test controls.

    Built by hand rather than taken from the shipped reference so that a test about
    the abort tripwire is not also a test about which screen id happens to be the
    shop this month. The shipped data is checked separately, against itself.
    """
    known = reference.KnownScreen(
        id=screen_id, name=name, purpose="for this test", verdict=verdict, why="because a test says so",
        identity_is_weak=False, animated_cells=0)
    return cr_session.Candidate(screen=screen_id, appearance=screen_id,
                                fingerprint=fingerprint_of(fill), volatile=frozenset(),
                                carried=known)


@pytest.fixture
def fake_harness(monkeypatch):
    """Swap `_harness` for fakes, so nothing here needs a window or a Win32 API."""
    def install(controller):
        battle = FakeBattle(controller)
        monkeypatch.setattr(cr_session, "_harness", lambda: (None, battle, None, FakeRecon))
        return controller
    return install


def test_a_frame_matching_nothing_carried_is_named_for_that(fake_harness):
    """`unknown-1` rather than `start`: the name is a claim about what was checked,
    and "not one of the measured screens" is the claim actually being made."""
    controller = fake_harness(FakeController([frame(0x10)]))
    session = cr_session.Session(controller=controller, candidates=[])

    first = session.observe()
    assert (first.screen, first.known, first.carried) == ("unknown-1", False, False)
    assert "not in the carried reference" in first.label

    again = session.observe()
    assert (again.screen, again.known) == ("unknown-1", True)
    assert len(session.candidates) == 1


def test_an_unrecognised_frame_becomes_a_new_screen(fake_harness):
    controller = fake_harness(FakeController([frame(0x10), frame(0x90), frame(0x90)]))
    session = cr_session.Session(controller=controller, candidates=[])

    assert session.observe().screen == "unknown-1"
    second = session.observe()
    assert (second.screen, second.known) == ("unknown-2", False)
    assert session.observe().screen == "unknown-2"


def test_a_carried_screen_is_known_on_its_first_sighting(fake_harness):
    """The whole difference the reference makes to a prediction: `known_screen` stops
    meaning "this run has been here" and starts meaning "this is a mapped screen"."""
    controller = fake_harness(FakeController([frame(0x40)]))
    session = cr_session.Session(controller=controller,
                                 candidates=[carried("sc01", 0x40, name="home")])

    first = session.observe()
    assert (first.screen, first.known, first.carried) == ("sc01", True, True)
    assert first.first_sight is True
    assert first.label == "sc01 (home)"
    assert session.observe().first_sight is False, "only the first sighting is the first sighting"


def test_the_nearest_stored_appearance_wins_not_the_first_over_the_threshold(fake_harness):
    """Two meta-game screens share the whole navigation bar, so both can clear the
    cut against a third. First-match would make identity depend on the order a
    different session happened to discover things in - which for the carried screens
    is the order some earlier session happened to find them.

    So: `sc02` differs in 20 of 576 cells, which scores 0.965 and clears the 0.94
    cut, and it is deliberately listed first. `sc01` is an exact match.
    """
    nearly = bytearray(fingerprint_of(0x40))
    for cell in range(20):
        nearly[cell * 3:cell * 3 + 3] = b"\xff\xff\xff"
    controller = fake_harness(FakeController([frame(0x40)]))
    session = cr_session.Session(controller=controller, candidates=[
        cr_session.Candidate(screen="sc02", appearance="sc02",
                             fingerprint=bytes(nearly), volatile=frozenset()),
        carried("sc01", 0x40),
    ])

    where = session.observe()
    assert where.screen == "sc01" and where.agreement == 1.0


def test_a_board_aborts_instead_of_being_registered_as_a_screen(fake_harness):
    """The tripwire, and the reason it is checked before identification: a board
    would otherwise become an ordinary unknown screen and the run would keep tapping
    at it. Scope is the meta-game, so this is unrecoverable by design."""
    controller = fake_harness(FakeController([frame(0x77)], pink=0.5))
    session = cr_session.Session(controller=controller, candidates=[])

    with pytest.raises(Unsafe) as raised:
        session.observe()
    assert "battle is in progress" in str(raised.value)
    assert session.candidates == []


def test_a_screen_classified_abort_stops_the_run(fake_harness):
    """The tripwire the carried data bought. Before it, a run that reached a purchase
    flow would have registered it as an ordinary unknown screen, recovered from it,
    and produced a report that read clean."""
    controller = fake_harness(FakeController([frame(0x30)]))
    session = cr_session.Session(controller=controller, candidates=[
        carried("sc08", 0x30, verdict="abort", name="Offers / Shop screen")])

    with pytest.raises(Unsafe) as raised:
        session.observe()
    assert "sc08 (Offers / Shop screen)" in str(raised.value)
    assert "because a test says so" in str(raised.value), "the run says WHY it stopped"


def test_a_frame_of_the_wrong_size_is_refused_rather_than_compared(fake_harness):
    """The one comparison error that produces a plausible answer instead of a crash:
    `diff_cells` truncates to the shorter of the two, so a short frame scores against
    only the part that exists and can agree with anything - including the shop."""
    controller = fake_harness(FakeController([b"\x10\x10\x10\xff" * 4]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc08", 0x10)])

    with pytest.raises(Unsafe) as raised:
        session.observe()
    assert "not 1728" in str(raised.value) or "1728" in str(raised.value)


def test_a_guard_refusal_comes_back_as_a_result_not_an_exception(fake_harness):
    """The Driver is building a model of an interface. "That was refused, and here
    is the reason" is evidence it can use; a PermissionError out of the middle of a
    checkpoint is a run that died because the safety system worked."""
    action = CATALOGUE[0]
    box = {"box": (action.at[0] - 0.01, action.at[1] - 0.01, 0.02, 0.02), "why": "for this test"}
    controller = fake_harness(FakeController([frame(0x40)], denylist=[box]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc01", 0x40)])

    result = session.act(action.name)
    assert result["verdict"] == "refused"
    assert "for this test" in result["why"]
    assert result["screen_was"] == "same_screen"
    assert controller.clicks == [], "a refused action must not have been sent"


def test_an_action_that_changes_nothing_reports_same_screen(fake_harness):
    controller = fake_harness(FakeController([frame(0x40)]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc01", 0x40)])

    result = session.act(RECOVERY)
    assert result["screen_was"] == "same_screen"
    assert result["screen_before"] == result["screen_after"] == "sc01"
    assert controller.clicks == [BY_NAME[RECOVERY].at]


def test_returning_to_a_screen_already_seen_reports_known_screen(fake_harness):
    controller = fake_harness(FakeController([frame(0x40), frame(0x90), frame(0x90), frame(0x40)]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc01", 0x40)])

    session.observe()                                 # the carried main screen
    assert session.observe().screen == "unknown-1"    # somewhere unmapped, discovered
    result = session.act("open_cards")                # and back again
    assert result["screen_was"] == "known_screen"
    assert result["screen_after"] == "sc01"


def test_execute_test_recovers_after_landing_somewhere_new(monkeypatch, fake_harness):
    """Recovery is part of executing a test, not a step after it. Without it the
    next test in the batch starts from wherever the last one ended, and the batch's
    result depends on the order it happened to run in - which the casting prompt
    promises the Driver is not the case."""
    controller = fake_harness(FakeController([frame(0x40), frame(0x90), frame(0x40)]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc01", 0x40)])
    monkeypatch.setattr(cr_session, "_SESSIONS", {"live": session})
    monkeypatch.setattr(cr_session.reference, "MAIN_SCREEN", "sc01")

    result = cr.execute_test(
        {"action": "open_profile", "predicted_screen": "new_screen", "predicted_outcome": "a panel"},
        7,
    )

    assert result["actual_screen"] == "new_screen"
    assert result["prediction_matched"] is True
    assert result["result"]["recovered_to"] == "sc01"
    assert controller.clicks == [BY_NAME["open_profile"].at, BY_NAME[RECOVERY].at]


def test_a_recovery_that_does_not_reach_the_main_screen_says_so(fake_harness, monkeypatch):
    """The most important thing a log can say: the run is somewhere nobody chose, so
    the next test did not start where it thought it did. Only answerable at all
    because the home screen has a measured fingerprint - in a fresh run no name means
    anything, which is why this could not be checked before the reference existed."""
    controller = fake_harness(FakeController([frame(0x90)]))
    session = cr_session.Session(controller=controller,
                                 candidates=[carried("sc01", 0x40, name="home")])
    monkeypatch.setattr(cr_session.reference, "MAIN_SCREEN", "sc01")
    monkeypatch.setitem(cr_session.reference.BY_ID, "sc01",
                        carried("sc01", 0x40, name="home").carried)

    where = session.recover()
    assert "NOT the main screen" in where and "sc01 (home)" in where


def test_execute_test_does_not_recover_when_nothing_moved(monkeypatch, fake_harness):
    """The other half: a tap that changed nothing has not left the client anywhere,
    so a recovery tap would be an extra unexplained input in the log."""
    controller = fake_harness(FakeController([frame(0x40)]))
    session = cr_session.Session(controller=controller, candidates=[carried("sc01", 0x40)])
    monkeypatch.setattr(cr_session, "_SESSIONS", {"live": session})

    result = cr.execute_test(
        {"action": "dismiss", "predicted_screen": "new_screen", "predicted_outcome": "something"},
        3,
    )

    assert result["actual_screen"] == "same_screen"
    assert result["prediction_matched"] is False
    assert "recovered_to" not in result["result"]
    assert controller.clicks == [BY_NAME["dismiss"].at]


def test_executing_a_test_before_readiness_ran_is_refused(monkeypatch):
    """`check_sut_ready` is what proves the guard is loaded and the client is
    off-board, so a session that appeared without it is a session nothing vetted.
    Raises rather than attaching lazily, which would be exactly the convenience
    that skips the preflight."""
    monkeypatch.setattr(cr_session, "_SESSIONS", {})
    with pytest.raises(Unsafe) as raised:
        cr_session.live()
    assert "check_sut_ready must run" in str(raised.value)


def test_an_action_name_that_slipped_past_the_schema_is_skipped_not_crashed(monkeypatch):
    """Unreachable through the enum and validation both, and handled anyway: this
    is the one place an unknown name would become a KeyError mid-checkpoint,
    discarding every result in the batch."""
    monkeypatch.setattr(cr_session, "_SESSIONS", {})
    result = cr.execute_test(
        {"action": "buy_gems", "predicted_screen": "new_screen", "predicted_outcome": "z"}, 1)
    assert result["skipped"] is True
    assert result["prediction_matched"] is False
    assert "not in the action catalogue" in result["skip_reason"]


# --- the report renders every outcome ----------------------------------------

@pytest.mark.parametrize("result, expected", [
    ({"verdict": "refused", "why": "denylisted: the Shop tab", "screen_before": "start",
      "screen_after": "start", "screen_was": "same_screen", "settle": 0.0},
     "refused by the coordinate guard"),
    ({"verdict": "sent", "screen_before": "start", "screen_after": "screen-2",
      "screen_was": "new_screen", "agreement": 0.42, "settle": 0.9,
      "recovered_to": "start"},
     "recovered to"),
])
def test_the_report_renders_each_kind_of_outcome(result, expected):
    """Every branch of `render_test_entry`, because a report is written once at the
    end of a run that cost real time on a real account - a KeyError there loses the
    readable half of the output."""
    html = cr.render_test_entry({
        "test_number": 1, "linked_hypothesis": "", "request": {"action": RECOVERY, "at": [0.5, 0.9]},
        "predicted_outcome": "p", "predicted_screen": "same_screen",
        "actual_screen": result["screen_was"], "prediction_matched": False, "result": result,
    })
    assert expected in html


def test_the_report_renders_a_skipped_test():
    html = cr.render_test_entry({
        "test_number": 2, "linked_hypothesis": "", "request": {"action": "buy_gems"},
        "predicted_outcome": "p", "predicted_screen": "new_screen",
        "skipped": True, "skip_reason": "not in the catalogue",
    })
    assert "skipped" in html and "not in the catalogue" in html


def test_the_onboarding_section_includes_the_preflight_report():
    """The operator's rule is that the denylist is shown, and a run is reviewed from
    its report long after the console scrollback is gone."""
    html = cr.render_onboarding_section(
        cr.API_SCHEMA_DOC, {"preflight": "SAFETY PREFLIGHT TEXT"},
        {"request": {"action": RECOVERY}, "response": {"verdict": "sent"}})
    assert "SAFETY PREFLIGHT TEXT" in html


@pytest.mark.parametrize("baseline, expected", [
    ("Started on sc01 (home), agreement 0.998.", "main screen"),
    ("WARNING: the first frame matched NO carried screen", "unconfirmed"),
])
def test_the_onboarding_section_says_whether_the_start_was_confirmed(baseline, expected):
    """An unconfirmed baseline qualifies every finding under it, so it belongs beside
    them rather than in a scrollback: if the first frame matched no measured screen,
    every same_screen/new_screen below is relative to whatever happened to be up."""
    html = cr.render_onboarding_section(
        cr.API_SCHEMA_DOC, {"baseline": baseline},
        {"request": {"action": RECOVERY}, "response": {"verdict": "sent"}})
    assert baseline[:40] in html and expected in html


# --- the carried screen reference ---------------------------------------------

def test_the_shipped_reference_passes_its_own_check():
    """`check_reference` is the fail-closed gate `attach` runs, and it is written to
    refuse the failures that are silent: a file that loaded but has no abort screens
    gives a run a tripwire that matches nothing, and produces a clean report about a
    run that had no protection at all."""
    text = reference.check_reference()
    assert f"grid {reference.GRID_COLS}x{reference.GRID_ROWS}" in text
    assert "stops on sight" in text


def test_the_reference_still_classifies_the_screens_that_must_stop_a_run():
    """The concrete reason the data was carried. Named individually rather than
    counted, because "five abort screens" would still pass if the shop were replaced
    by something harmless."""
    aborts = {screen.id for screen in reference.ABORT_ON}
    assert {"sc03", "sc04", "sc05", "sc07", "sc08"} <= aborts
    shop = reference.BY_ID["sc03"]
    assert "Shop" in (shop.name or "") and shop.verdict == "abort"


def test_every_carried_screen_is_classified_and_every_verdict_is_one_of_two():
    """A screen with no verdict would be treated as ordinary, which would make the
    one screen nobody reviewed the one the run trusts. `extract_reference` refuses to
    write such a file; this is the assertion that the file on disk was written by it."""
    for screen in reference.KNOWN_SCREENS:
        assert screen.verdict in ("ok", "abort"), screen.id
        assert screen.why, screen.id


def test_the_main_screen_is_declared_and_is_not_one_the_run_aborts_on():
    """A run returns here after every discovery, so a main screen classified `abort`
    would abort the run on its own recovery."""
    home = reference.BY_ID[reference.MAIN_SCREEN]
    assert home.verdict == "ok"


def test_every_carried_fingerprint_is_the_size_the_comparison_expects():
    """The failure this prevents does not raise: `diff_cells` truncates to the shorter
    of the two frames, so a wrong-sized fingerprint scores against a fraction of the
    screen and can agree with anything."""
    for screen in reference.KNOWN_SCREENS:
        for appearance in screen.appearances:
            assert len(appearance.fingerprint) == reference.NCELLS * 3, appearance.key


def test_no_two_carried_screens_are_confusable_at_the_carried_threshold():
    """The claim the whole reference rests on: that these fingerprints identify
    *different* screens. Two that agreed above the cut would mean every visit to one
    could be reported as the other - and if one of them is the shop, the tripwire
    would fire on an innocent screen, or fail to fire on the shop."""
    representatives = [(screen.id, screen.appearances[0]) for screen in reference.KNOWN_SCREENS]
    for i, (id_a, a) in enumerate(representatives):
        for id_b, b in representatives[i + 1:]:
            score, stable, _ = FakeRecon.agreement(
                a.fingerprint, b.fingerprint, a.volatile | b.volatile, reference.CELL_DELTA)
            assert score < reference.SCREEN_MATCH, (
                f"{id_a} and {id_b} agree at {score:.3f}, at or above the "
                f"{reference.SCREEN_MATCH} cut, on {stable} stable cells")


def test_the_driver_is_told_the_screens_are_a_prior_it_may_contradict():
    """The reference is a measurement with a date on it, taken against a client that
    updates itself. A Driver told these as facts would report a stale fingerprint as
    a navigation defect."""
    briefing = reference.driver_briefing()
    assert "PRIOR, not a fact" in briefing
    assert reference.SOURCE["pass"] in briefing
    assert "ABORTS" in briefing
    assert briefing in cr.API_SCHEMA_DOC, "and it actually reaches the Driver"


def test_an_unnamed_carried_screen_is_not_given_an_invented_name():
    """Three screens were seen and never labelled. Reporting `sc05` plainly is more
    honest than guessing, and a None leaking into a log as "None" is worse than both."""
    unnamed = [screen for screen in reference.KNOWN_SCREENS if screen.name is None]
    assert unnamed, "the carried pass had three of these; if that changed, check why"
    for screen in unnamed:
        assert screen.label == f"{screen.id} (unnamed)"
        assert "None" not in reference.driver_briefing().split(screen.id)[1][:200]


def test_the_carried_transitions_are_taps_only():
    """A drag is the only input that touches somewhere it was not aimed at, there is
    none in the action space, and the one recorded escape from this project's guard
    was a swipe. A carried prior for an input that cannot be sent is a fact the
    Driver can neither use nor check."""
    assert reference.TAP_TRANSITIONS
    for transition in reference.TAP_TRANSITIONS:
        assert set(transition) >= {"from", "to", "at", "effect", "settle_ms"}
        assert len(transition["at"]) == 2


def test_a_session_is_seeded_with_the_tripwire_screens_by_default():
    """The default matters more than it looks like it should: the failure mode of an
    unseeded session is that the shop screen looks ordinary, so a session anybody
    constructs without thinking about it has to be the safe one."""
    session = cr_session.Session(controller=None)
    screens = {candidate.screen for candidate in session.candidates}
    assert {screen.id for screen in reference.ABORT_ON} <= screens
    assert len(session.candidates) > len(reference.KNOWN_SCREENS), "variants are carried too"


def test_the_session_uses_the_carried_grid_and_threshold_not_its_own():
    """These are not tuning parameters. The fingerprints were measured at 32x18 and
    matched at 0.94, and a different value here would mean comparing those
    measurements under conditions they were never taken under."""
    assert (cr_session.GRID_COLS, cr_session.GRID_ROWS) == (32, 18)
    assert cr_session.SAME_SCREEN == reference.SCREEN_MATCH


@pytest.fixture
def ready_harness(monkeypatch, fake_harness):
    """`check_ready` with the attach and the wall-clock taken out.

    Only those two: the elixir check, the idle-drift check and the baseline
    identification all run for real against the fake frames, because those are the
    three things being asserted. The real second of sleep is removed because a gate
    every run passes through is worth testing more than once per second.
    """
    def install(frames, candidates, *, pink=0.0):
        controller = fake_harness(FakeController(frames, pink=pink))
        session = cr_session.Session(controller=controller, candidates=candidates)
        monkeypatch.setattr(cr_session, "attach", lambda verbose=True: (session, "PREFLIGHT TEXT"))
        monkeypatch.setattr(cr_session.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(cr_session, "_SESSIONS", {})
        monkeypatch.setattr(cr_session.reference, "MAIN_SCREEN", "sc01")
        monkeypatch.setitem(cr_session.reference.BY_ID, "sc01",
                            carried("sc01", 0x40, name="home").carried)
        return session
    return install


class Recipient:
    """Somewhere for `check_ready` to write, standing in for the adapter."""
    def __init__(self):
        self.onboarding_extra: dict = {}


def test_readiness_records_the_baseline_when_the_run_starts_on_the_main_screen(ready_harness):
    session = ready_harness([frame(0x40)], [carried("sc01", 0x40, name="home")])
    adapter = Recipient()

    cr_session.check_ready(adapter)

    assert cr_session.live() is session
    assert adapter.onboarding_extra["preflight"] == "PREFLIGHT TEXT"
    assert adapter.onboarding_extra["baseline"].startswith("Started on sc01 (home)")


def test_readiness_refuses_when_the_client_is_on_a_known_screen_that_is_not_home(ready_harness):
    """The hole the reference closed. A run starting on the deck screen would take
    that as its baseline, and `open_cards` would then read `same_screen` while
    `return_to_main` read `new_screen` - two findings, both artefacts, and the
    mislabelling propagates through every checkpoint. Nothing about a single frame
    could catch this before there were measured fingerprints to compare it to."""
    ready_harness([frame(0x70)], [carried("sc01", 0x40, name="home"),
                                  carried("sc02", 0x70, name="Battle Deck")])

    with pytest.raises(SystemExit) as raised:
        cr_session.check_ready(Recipient())
    assert "not on sc01 (home)" in str(raised.value)
    assert "Nothing was tapped" in str(raised.value)
    assert cr_session._SESSIONS == {}, "a refused readiness must not leave a live session behind"


def test_readiness_warns_but_continues_when_no_carried_screen_matches(ready_harness):
    """Deliberately not a refusal. This is a labelling check, not a safety one - the
    guard, the board tripwire and the abort screens are all still in force - and the
    likeliest cause is a stale reference, since the client updates itself. Refusing
    would mean one game update makes the adapter unrunnable until somebody regenerates
    a recon pass."""
    ready_harness([frame(0x99)], [carried("sc01", 0x40, name="home")])
    adapter = Recipient()

    cr_session.check_ready(adapter)

    note = adapter.onboarding_extra["baseline"]
    assert note.startswith("WARNING")
    assert "unknown-1" in note and "gone stale" in note


def test_readiness_refuses_a_client_that_is_already_in_a_battle(ready_harness):
    """Ahead of the baseline check on purpose: the scope rule does not depend on
    recognising a screen, and a board has no carried fingerprint at all."""
    ready_harness([frame(0x40)], [carried("sc01", 0x40)], pink=0.5)

    with pytest.raises(SystemExit) as raised:
        cr_session.check_ready(Recipient())
    assert "battle is already in progress" in str(raised.value)


def test_readiness_refuses_a_window_that_is_still_moving(ready_harness):
    """A frame caught mid-transition is a picture of a transition, and would be
    matched against as though it were a place."""
    ready_harness([frame(0x40), frame(0x90)], [carried("sc01", 0x40)])

    with pytest.raises(SystemExit) as raised:
        cr_session.check_ready(Recipient())
    assert "mid-transition or still loading" in str(raised.value)


def test_the_fake_recon_agrees_with_the_real_one():
    """These session tests run against a reimplementation of `recon.agreement`, which
    is only safe while the copy matches. Skips where `recon` cannot be imported -
    it reaches Win32 - so this is the Windows half of the same claim."""
    recon = pytest.importorskip("recon")
    assert recon.MIN_STABLE_CELLS == FakeRecon.MIN_STABLE_CELLS
    assert recon.NCELLS == FakeRecon.NCELLS

    a = reference.KNOWN_SCREENS[0].appearances[0]
    b = reference.KNOWN_SCREENS[1].appearances[0]
    for left, right, mask in ((a, a, a.volatile), (a, b, a.volatile), (b, a, frozenset())):
        assert recon.agreement(left.fingerprint, right.fingerprint, set(mask),
                               reference.CELL_DELTA) == FakeRecon.agreement(
            left.fingerprint, right.fingerprint, mask, reference.CELL_DELTA)
