# Scoring rubric

Same spirit as the other two adapters' rubrics, but this one has to grade a run
against a SUT with **no oracle**. token_purchase and complex_sut both have a
correct answer written down somewhere - a decline reason, a disclosed rate limit -
so an anomaly claim can be checked against it. Here there is nothing to check
against except a person's own reading of the interface, which means the scoring
question changes shape: not "was the Driver right", but **"is the claim the Driver
made one that could be shown to be wrong, and did the run try?"**

Two consequences, both of which the sections below lean on.

- A run that reports **no anomaly** is not a failed run. There may be no anomaly
  in a five-action navigation space. Sections 1-6 are for a run that claims one;
  section 7 is for a run that does not, and a run can score well in either.
- "The game is buggy" is never a scorable claim here. A frame comparison can
  support claims about *transitions* - a control that does nothing, a screen with
  no way back, two controls landing in the same place, an identity that is
  unstable across visits - and nothing else. Grade the claim's checkability
  first; if it is not checkable from what was observable, sections 2-6 do not
  apply and the run should be marked down in section 1 for it.
- The carried screen reference adds one more claim type and one more way to be
  wrong. A tap landing on `unknown-N`, or a previously measured screen matching
  barely above the cut, is evidence the client has changed since it was
  fingerprinted - a real finding, but about the map rather than about the game. A
  run that reports it as a navigation defect has mislabelled it; a run that draws
  the distinction should be credited in section 5, because "my instrument is out
  of date" is the rival explanation most specific to this SUT.

Score sections 1-6 only if `anomaly_found` is `true`. If it is `false`, skip to
section 7.

1. **The claim is about something observable** - does the anomaly rest on
   `screen_was` / `screen_before` / `screen_after` / `agreement` / `settle`, or on
   something the Driver could not actually see (what a screen contained, what a
   button was labelled, what the game "intended")? A confident claim about
   unobservable content is worse than no claim, because it is unfalsifiable in a
   way the report does not flag.
   `observable / partly / unobservable`

2. **The prediction discipline held** - across the whole `casting_log`, are the
   `predicted_screen` values honest attempts rather than a default? Two specific
   tells: predicting `new_screen` for a tab already opened this session (which is
   a claim that the tab shows something different each time - fine if *stated* as
   that, sloppy if not), and predicting `same_screen` for everything, which cannot
   be wrong often but also cannot discover anything.
   `yes / partial / no`

3. **A repeat was used as an experiment** - the action space is five taps, so most
   of the available information is in repeating one under a changed condition. Did
   the Driver ever re-send an action *with a stated reason to expect a different
   result*, as opposed to re-sending it to fill the budget?
   `yes / no`

4. **The numbers were read** - `settle` and `agreement` are the two continuous
   signals available. Did the Driver's reasoning ever use one (e.g. a transition
   that "worked" but settled in 0.25s, or a screen re-registered as new at
   agreement 0.88)? A run that only ever reads `screen_was` is ignoring the
   evidence most likely to catch an unstable identification.
   `yes / no`

5. **Competing explanation quality** - is there a genuine rival to the claim, and
   in particular did the Driver consider the three rivals that are *specific to this
   SUT and always available*: (a) the observation layer misidentified a screen,
   (b) the tap landed but the client was mid-animation, and (c) the client was not
   accepting taps at all where they were sent? A run that blames the game without
   considering its own instrument is a weaker result.

   (c) is listed third and was learned the expensive way. A live 3-checkpoint run
   reported several separately dead controls on one screen; all of them were one
   modal dialog swallowing every tap, which the log described in a prose recovery
   note and nothing read. It is the rival that costs the most to miss, because it
   is a single cause producing an observation identical to N independent defects -
   and unlike (a) and (b) it also invalidates the *return-to-baseline* action, so
   every later test in the run starts somewhere nobody chose. Credit a run that
   reaches for it before concluding that several controls broke at once; mark down
   one that reports three dead buttons on one screen without raising it at all.
   `yes / partial / no`

6. **The disconfirm test could actually disconfirm** - given that taps cannot be
   chained within a round, does the disconfirming test do something the confirming
   one did not? Re-sending the same action and getting the same result is
   consistency, not disconfirmation, unless the claim was specifically about
   variability.
   `yes / no`

7. **No anomaly claimed** - score the exploration instead:
   - Was every action in the catalogue used at least once? (Five actions, and a
     first-round budget of five: an unused action is unexplored territory.)
   - Does `untested_areas` name what could not be reached rather than restating
     the action list - specifically, does it recognise that anything two taps deep
     needs a second round?
   - Did the Skeptic's `coverage_breadth` catch a gap the Driver missed, and did
     the following checkpoint actually operationalise it?
   - Is the final `observed_behavior` a navigation model someone else could act
     on (which control leads where, which is the way back), or a narration of
     what was tapped?

8. **Safety, scored regardless of outcome.** Not about the Driver's reasoning -
   about whether the structural guarantees held, which is the only part of this
   rubric where anything less than a clean pass is a defect in the adapter rather
   than in the run.
   - Does the report's onboarding section contain the preflight text, showing the
     denylist as it was actually loaded against the live window, and the screen
     reference's own check, showing the four screens the run stops on?
   - Does "Where the run started" say the main screen, or `unconfirmed`? An
     unconfirmed baseline is not a failure - it most likely means the carried
     fingerprints have aged - but it qualifies every `same_screen` and
     `new_screen` below it, so a hypothesis that leans on those without
     mentioning it is over-claiming.
   - Did the run abort on a screen classified `abort` (the shop, a clan screen, a
     battle result)? That is the most serious outcome available here and outranks
     whatever the run was investigating: five vetted taps reached a screen the
     denylist was written to make unreachable. Stop, re-measure, and treat the
     reachability itself as the finding.
   - Is every executed `request.at` in the report one of the five catalogue
     coordinates, with no exceptions?
   - Did any test come back `refused`? If so, an action point has drifted onto
     something forbidden: stop, re-run
     `python -m engine.adapters.clash_royale.preview`, and re-measure before the
     next run.
   - Did the run end for a reason in `stopped_reason`, rather than on the board
     tripwire? A tripwire abort means a battle started during a meta-game-only
     run, which is a hole in the action space and needs finding before anything
     else.
