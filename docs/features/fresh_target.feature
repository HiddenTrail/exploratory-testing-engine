# A fresh target before each run of an experiment (#372).
#
# The local Juice Shop kept baskets, reviews and users between runs, and after a restart
# it refused parts of an old session (#360). The runs of an experiment should start from
# the same, fresh target.
#
# #372 also asked for a temperature setting, the other cheap source of run-to-run noise.
# Our model, Sonnet 5 on Bedrock, has none: the API answers "`temperature` is deprecated
# for this model" (checked 2026-10-08), and the SDK's messages.create has no such
# parameter. Noise is cut by the design of an experiment instead (#369): re-judging saved
# runs, one round at a time, rates over many items.
#
# Code: trailhound/adapters/web_gui/fresh_target.py. Tests: trailhound/tests/test_fresh_target.py

Feature: A fresh target before each run of an experiment
  As someone comparing two versions of the engine
  I want each run to start from the same, freshly restarted target and a fresh login
  So that what earlier runs left behind doesn't change the result

  Scenario: Restart and log in fresh
    When python -m trailhound.adapters.web_gui.fresh_target --container test-targets-juice-shop-1 --url http://127.0.0.1:3000 --recipe test-targets/login-recipes/juice-shop.json --product juice-shop runs
    Then docker restarts the container, it waits up to 120 s for the URL to answer 200, and it logs in fresh from the recipe as "logged-in"
    And without --recipe it only restarts and waits

  Scenario: Only a test target is restarted
    Given a container without the label trailhound.sandbox=true
    Then it is never restarted: "... isn't labelled trailhound.sandbox=true, so it isn't restarted"
    And one made before the rename to Trailhound, with qes.sandbox, is told how to remake it with docker compose
    And a container docker doesn't know stops it, and so does a target that doesn't answer in time
    And the login recipe only runs against this machine, as always
