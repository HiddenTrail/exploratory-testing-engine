"""Test fully by default, and be careful only where tagged (issue #299). Pure: no browser."""

import json

from engine.adapters.web_gui import careful


def test_tags_come_from_the_targets_file_and_the_runs_setting(tmp_path):
    (tmp_path / "shop.json").write_text(json.dumps({"routes": ["/#/payment"], "controls": ["Delete account"]}))
    tags = careful.load("shop", env="/#/admin, Close account", careful_dir=tmp_path)
    assert tags == {"everything": False, "routes": ["/#/payment", "/#/admin"],
                    "controls": ["Delete account", "Close account"]}
    assert careful.load("other", env="", careful_dir=tmp_path) == careful.NOTHING
    assert careful.load("", env="*", careful_dir=tmp_path)["everything"] is True


def test_a_step_is_careful_on_a_tagged_route_or_control():
    tags = {"everything": False, "routes": ["/#/payment"], "controls": ["delete account"]}
    assert careful.applies(tags, route="/#/payment")
    assert careful.applies(tags, route="#/payment/confirm")             # a route under it, with or without "/"
    assert not careful.applies(tags, route="/#/basket")
    assert careful.applies(tags, route="/#/profile", name="Delete Account")
    assert not careful.applies(careful.NOTHING, route="/#/payment", name="Delete account")
    assert careful.applies(careful.EVERYTHING)


def test_logging_out_is_recognised_in_its_usual_spellings():
    for text in ("Logout", "Log out", "sign out", "/rest/user/logout", "Log off"):
        assert careful.logs_out(text), text
    assert not careful.logs_out("Login") and not careful.logs_out("Catalog")


def test_a_run_says_how_far_it_may_go():
    assert careful.describe(careful.NOTHING) == "Testing fully: nothing on this target is tagged careful."
    assert careful.describe({"everything": False, "routes": ["/#/payment"], "controls": []}) == (
        "Testing fully, except where tagged careful (routes /#/payment): there the Driver only looks.")
    assert careful.describe(careful.EVERYTHING).startswith("Careful: this whole target is tagged careful")
