"""What `make_vetter` does with an answer that is the wrong shape, which is not rare.

A vetting call's reply is a tool call, and a tool call cut off at `max_tokens` arrives as
*partial* JSON: schema shaped, holding whatever came first, missing whatever came last.
`VET_TOOL` marking a field required does not make it present - the schema describes what
was asked for, not what came back.

Two of those on one five-minute pass against Clash Royale each cost a whole batch of
candidates, because the verdict was assembled from fields nothing had checked:
`KeyError('name')` from a reply truncated before the name, and `'str' object has no
attribute 'get'` from an `actions` list that came back as bare strings. The second was
raised *inside* the validator, where it could not even be reported as a bad answer.

So the rule these tests hold: an answer this code cannot use is a **validation failure**,
never an exception. That is the difference between a retry - `call_tool_with_retry` feeds
the model its own malformed call back, and asks for a terser one when the reason was
length - and a lost batch. The exception is `elements`, which is a description rather
than a permission and is allowed to be partly lost; the last test is that trade.

No network: the client is a stub, in the shape `engine/tests/test_client_retry.py` uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # for `engine.client`

import pytest

import describe
from recon import Action, Screen, Variant


class FakeToolUse:
    def __init__(self, payload: dict) -> None:
        self.type = "tool_use"
        self.id = "tu_1"
        self.input = payload


class FakeMessage:
    def __init__(self, payload: dict, stop_reason: str = "tool_use") -> None:
        self.content = [FakeToolUse(payload)]
        self.stop_reason = stop_reason
        self.usage = None


class FakeMessages:
    def __init__(self, replies: list[FakeMessage]) -> None:
        self._replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        # The last reply repeats, so a test can say "it keeps answering like this"
        # without counting attempts - the point of those tests is that the batch is
        # given up on, not how many times it was asked for.
        return self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]


class FakeClient:
    def __init__(self, *replies: FakeMessage) -> None:
        self.messages = FakeMessages(list(replies))


CANDIDATES = (Action(kind="click", at=(0.50, 0.40)),
              Action(kind="key", key="escape"))


def verdicts(safe: bool = True) -> list[dict]:
    return [{"action_id": a.id, "safe": safe, "why": "test"} for a in CANDIDATES]


def whole(**overrides) -> dict:
    """A well-formed answer, which every malformed one below is a single edit away from.

    Written as a base rather than per test so that what each test is about is the one
    field it changes - a test that spelled out its own payload would leave the reader
    diffing two dictionaries to find the defect under examination.
    """
    payload = {"name": "Lobby", "purpose": "the main screen", "highlighted": "",
               "elements": [{"label": "Battle", "what": "starts a match",
                             "box": [0.30, 0.70, 0.40, 0.10]}],
               "actions": verdicts()}
    payload.update(overrides)
    return payload


def vet_with(*replies: FakeMessage, tmp_path: Path):
    """Run one vetting call against `replies`, and hand back the client too.

    The image is a file with nothing in it: `image_block` only base64-encodes the bytes,
    and no stub ever looks at them. What is being tested is on the reply side.
    """
    shot = tmp_path / "sc01.png"
    shot.write_bytes(b"not really a png")
    client = FakeClient(*replies)
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    variant = Variant(id="sc01v1", key="k", fp=b"")
    screen.variants[variant.id] = variant
    vet = describe.make_vetter(model="test-model", client=client)
    return vet, (shot, screen, variant, CANDIDATES), client


def test_a_reply_cut_off_before_the_name_is_a_bad_answer_and_not_a_crash(tmp_path):
    """The first live failure. `actions` came back complete and `name` never arrived, so
    the old validator - which read nothing but the action ids - passed it, and the verdict
    was assembled straight into `KeyError('name')`.

    Truncation is why the reply is checked for fields the schema already marks required,
    and `stop_reason` is why it is worth reaching the retry: `call_tool_with_retry` asks a
    reply that ran out of room for a shorter one, rather than for the same one again.
    """
    cut = whole()
    del cut["name"]
    vet, args, client = vet_with(FakeMessage(cut, stop_reason="max_tokens"),
                                FakeMessage(whole()), tmp_path=tmp_path)

    answer = vet(*args)

    assert client.messages.calls[0]["max_tokens"] == describe.VET_MAX_TOKENS
    assert len(client.messages.calls) == 2, "the bad reply should have been retried"
    assert answer["name"] == "Lobby"
    assert set(answer["actions"]) == {a.id for a in CANDIDATES}


def test_verdicts_that_came_back_as_bare_strings_are_a_bad_answer(tmp_path):
    """The second live failure, and the worse of the two: the old validator called
    `.get` on each entry, so a list of strings raised `AttributeError` *inside the
    validator*. A validator that can raise cannot report, and the machinery that would
    have asked for a better answer never ran.

    The retry is fed the concrete complaint, which is why the message names the type it
    got rather than just refusing.
    """
    strings = whole(actions=[a.id for a in CANDIDATES])
    vet, args, client = vet_with(FakeMessage(strings), FakeMessage(whole()),
                                tmp_path=tmp_path)

    answer = vet(*args)

    assert len(client.messages.calls) == 2
    assert answer["actions"][CANDIDATES[0].id]["safe"] is True
    # The complaint went back as a tool_result, in the words the validator wrote.
    fed_back = str(client.messages.calls[1]["messages"])
    assert "not an object with action_id, safe and why" in fed_back


@pytest.mark.parametrize("bad, complaint", [
    ({"actions": {"click:0.500,0.400": True}}, "must be a list of verdicts"),
    ({"actions": [{"action_id": CANDIDATES[0].id, "safe": "yes", "why": "test"},
                  {"action_id": CANDIDATES[1].id, "safe": True, "why": "test"}]},
     "needs safe as a bool"),
    ({"actions": [{"action_id": CANDIDATES[0].id, "safe": True}] + verdicts()[1:]},
     "needs why as a str"),
    ({"purpose": ""}, "'purpose' must be a non-empty string"),
])
def test_every_field_the_verdict_reads_is_refused_before_it_is_read(bad, complaint,
                                                                   tmp_path):
    """One case per field the return statement touches. Each of these is a payload that
    would have got through a validator that only counted action ids, and each would then
    have raised somewhere else - a `TypeError` on a dict, a `safe` the policy code
    compares as a string, a missing `why` that is what a refusal *says*.

    A wrong `safe` is the one worth spelling out: `"yes"` is truthy, so an action the
    model meant to refuse would read as permitted. That is a safety floor failing quietly,
    which is the failure mode this whole file exists to make loud.
    """
    vet, args, client = vet_with(FakeMessage(whole(**bad)), tmp_path=tmp_path)

    with pytest.raises(RuntimeError, match="Gave up after"):
        vet(*args)

    assert complaint in str(client.messages.calls[1]["messages"])


def test_a_malformed_element_is_dropped_and_the_rest_of_the_answer_kept(tmp_path, capsys):
    """The one field allowed to come back partly broken, and why it is the only one.

    A verdict decides what may be pressed; an element is a *description*, and losing one
    costs a label and a crop on a screen whose actions were ruled on either way. Retrying
    a whole batch of candidates over a bad element entry would trade something that
    matters for something that does not - the same trade `locate_elements` already makes
    for an element whose box it cannot measure. It is dropped, it is said out loud, and
    the pass goes on.
    """
    ragged = whole(elements=["Battle", {"label": "Shop", "what": "sells things",
                                        "box": [0.6, 0.9, 0.2, 0.08]}, None])
    vet, args, client = vet_with(FakeMessage(ragged), tmp_path=tmp_path)

    answer = vet(*args)

    assert len(client.messages.calls) == 1, "an element must not cost a retry"
    assert [e["label"] for e in answer["elements"]] == ["Shop"]
    assert "dropped 2 of 3 described elements on sc01" in capsys.readouterr().out


def test_elements_missing_altogether_is_a_screen_with_no_elements(tmp_path):
    """Not the same as a broken one, and not an error either: `elements` is optional in
    fact if not in the schema, and a screen the model found nothing nameable on is an
    ordinary outcome. What must not happen is `None` reaching the map, where every reader
    of `screen.vetting["elements"]` iterates it."""
    vet, args, _ = vet_with(FakeMessage(whole(elements=None)), tmp_path=tmp_path)

    assert vet(*args)["elements"] == []
