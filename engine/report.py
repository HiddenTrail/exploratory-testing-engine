"""Renders a run's output.json (+ bugs.json, if present) as a single
self-contained HTML file - everything the JSON contains, laid out for a
human to actually read checkpoint by checkpoint, instead of scrolling raw
JSON. ~70% of this was already identical across every prior experiment's
report.py (markdown-lite prose rendering, badges, CSS, page/checkpoint
structure) - that part lives here, generic and adapter-agnostic. The
genuinely per-SUT parts (how to render one test entry, how to render the
onboarding/schema section) are supplied by the adapter.

esc/inline_markdown/render_prose/badge/bool_badge/verdict_badge/
render_json_block/CSS are public so adapter render_test_entry/
render_onboarding_section implementations, and other report renderers
(e.g. engine.bootstrap.report), can reuse them.
"""

import html
import json
import re
from pathlib import Path

from engine.adapter import SUTAdapter


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`(.+?)`")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)")


def inline_markdown(text: str) -> str:
    escaped = esc(text)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def render_prose(text) -> str:
    """The Driver and Skeptic write markdown-flavored prose (headers, **bold**,
    `code`, bullet lists) in every free-text field - this is a small, deliberately
    narrow markdown->HTML pass covering just what these fields actually contain,
    not a general markdown parser."""
    if not text:
        return ""
    html_parts = []
    list_buffer = []
    paragraph_buffer = []

    def flush_list():
        if list_buffer:
            html_parts.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_buffer) + "</ul>")
            list_buffer.clear()

    def flush_paragraph():
        if paragraph_buffer:
            html_parts.append(f"<p>{' '.join(paragraph_buffer)}</p>")
            paragraph_buffer.clear()

    for raw_line in str(text).strip().split("\n"):
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        header_match = _HEADER_RE.match(line)
        if header_match:
            flush_paragraph()
            flush_list()
            level = min(len(header_match.group(1)) + 3, 6)
            html_parts.append(f"<h{level}>{inline_markdown(header_match.group(2))}</h{level}>")
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            flush_paragraph()
            list_buffer.append(inline_markdown(bullet_match.group(1)))
            continue

        flush_list()
        paragraph_buffer.append(inline_markdown(line))

    flush_paragraph()
    flush_list()
    return "".join(html_parts)


def badge(text, kind) -> str:
    return f'<span class="badge badge-{kind}">{esc(text)}</span>'


def bool_badge(value, true_label="yes", false_label="no") -> str:
    if value is True:
        return badge(true_label, "good")
    if value is False:
        return badge(false_label, "bad")
    return badge("unknown", "warn")


def verdict_badge(verdict) -> str:
    kind = {
        "corroborated": "good",
        "inconclusive": "warn",
        "strong_enough": "good",
        "weak": "bad",
    }.get(verdict, "warn")
    return badge(verdict.replace("_", " ") if verdict else "unknown", kind)


def render_json_block(data) -> str:
    return f'<pre class="payload">{esc(json.dumps(data, ensure_ascii=False))}</pre>'


def _tests_label(tests) -> str:
    if not tests:
        return ""
    return f'<span class="prose-muted">(tests {", ".join(f"#{n}" for n in tests)})</span>'


def _check_badge(check) -> str:
    if not check:
        return ""
    return bool_badge(check["discriminates_from_rival"], "discriminates", "doesn't discriminate")


def _lowered_label(observation) -> str:
    if "driver_kind" not in observation:
        return ""
    return f' <span class="prose-muted">(the Driver said {esc(observation["driver_kind"])}, the Skeptic lowered it)</span>'


def _observation_line(observation, check) -> str:
    return (
        f'<li><span class="idtag">{esc(observation["id"])}</span> {esc(observation["kind"])} '
        f'({esc(observation["severity"])}) {inline_markdown(observation["claim"])} '
        f'{_tests_label(observation["tests"])} {_check_badge(check)}{_lowered_label(observation)}</li>'
    )


def _gap_line(gap) -> str:
    blocks = f" {badge('blocks verdict', 'bad')}" if gap["blocks_verdict"] else ""
    return (
        f'<li><span class="idtag">{esc(gap["id"])}</span> {inline_markdown(gap["gap"])}{blocks}'
        f'<div class="prose-muted">Next test: {inline_markdown(gap["next_test"])}</div></li>'
    )


def _prior_gaps_line(prior_gaps, prior_gaps_check) -> str:
    """One sentence for the whole continuity check, e.g. 'Prior gaps: 3 tested,
    2 not attempted. The Skeptic accepted 3 of 5 answers.'"""
    if not prior_gaps:
        return ""
    statuses = {}
    for g in prior_gaps:
        statuses[g["status"]] = statuses.get(g["status"], 0) + 1
    answered = ", ".join(f"{n} {status.replace('_', ' ')}" for status, n in statuses.items())
    accepted = sum(1 for c in prior_gaps_check if c["accepted"])
    return (f'<p class="prose-muted">Prior gaps: {esc(answered)}. The Skeptic accepted '
            f'{accepted} of {len(prior_gaps_check)} answers.</p>')


def _observation_details(observation, check) -> str:
    ruled_out = "ruled out" if observation.get("rival_ruled_out") else "not ruled out"
    rows = [
        ("Violates", observation.get("violates")),
        ("Reproduced", observation.get("reproduced")),
        ("Mechanism", observation.get("mechanism")),
        ("Rival", f"{observation.get('rival', '')} ({ruled_out} by the Driver)"),
        ("Why", observation.get("why")),
        ("Skeptic", (check or {}).get("note")),
    ]
    items = "".join(f"<li><strong>{label}:</strong> {inline_markdown(value)}</li>" for label, value in rows if value)
    return f'<p><span class="idtag">{esc(observation["id"])}</span></p><ul>{items}</ul>'


def _prior_gap_detail(gap, skeptic_check) -> str:
    judged = ""
    if skeptic_check:
        judged = (f" {bool_badge(skeptic_check['accepted'], 'accepted', 'not accepted')} "
                  f"{inline_markdown(skeptic_check['note'])}")
    return (f'<li><span class="idtag">{esc(gap["gap_id"])}</span> {esc(gap["status"].replace("_", " "))} '
            f'{_tests_label(gap["tests"])} {inline_markdown(gap["reason"])}{judged}</li>')


def _render_checkpoint(checkpoint_num, checkpoint_entry, rounds, render_test_entry) -> str:
    """One checkpoint, conclusion first. What a reader needs is visible: the
    verdict, the Driver's one-sentence summary, the Skeptic's one-sentence
    reason, one line per observation and one line per gap. Everything else -
    behaviors, each observation's mechanism and rival, coverage, the prior-gap
    answers, and the tests themselves - is folded underneath. Fully generic: the
    hypothesis/Skeptic schema is the same for every adapter."""
    test_count = sum(len(entries) for entries in rounds.values())
    tests_fold = f"""
      <details class="fold">
        <summary>Tests this checkpoint ({test_count})</summary>
        {_render_rounds(rounds, render_test_entry)}
      </details>"""
    if not checkpoint_entry:
        return f'<div class="checkpoint"><h3>Checkpoint {checkpoint_num}</h3>{tests_fold}</div>'

    hypothesis = checkpoint_entry["hypothesis"]
    skeptic = checkpoint_entry["skeptic_review"]
    observations = hypothesis["observations"]
    checks = {c["observation_id"]: c for c in skeptic["observation_checks"]}

    if observations:
        observations_html = ('<ul class="line-list">'
                             + "".join(_observation_line(o, checks.get(o["id"])) for o in observations) + "</ul>")
    else:
        observations_html = '<p class="prose-muted">Nothing looked wrong this checkpoint.</p>'
    gaps_html = ""
    if skeptic["gaps"]:
        gaps_html = ('<p><strong>Gaps and the tests that would close them</strong></p><ul class="line-list">'
                     + "".join(_gap_line(g) for g in skeptic["gaps"]) + "</ul>")

    behaviors = "".join(
        f"<li>{inline_markdown(b['claim'])} {_tests_label(b['tests'])}</li>" for b in hypothesis["behaviors"])
    untested = "".join(f"<li>{inline_markdown(u['area'])}</li>" for u in hypothesis["untested"])
    coverage = skeptic["coverage"]
    untouched = "".join(f"<li>{inline_markdown(a)}</li>" for a in coverage["untouched"])
    skeptic_checks = {c["gap_id"]: c for c in skeptic["prior_gaps_check"]}
    prior = "".join(_prior_gap_detail(g, skeptic_checks.get(g["gap_id"])) for g in hypothesis["prior_gaps"])

    details = []
    if behaviors:
        details.append(f"<p><strong>Confirmed behavior</strong></p><ul>{behaviors}</ul>")
    if observations:
        details.append("<p><strong>Observations in detail</strong></p>"
                       + "".join(_observation_details(o, checks.get(o["id"])) for o in observations))
    if untested:
        details.append(f"<p><strong>Untested, according to the Driver</strong></p><ul>{untested}</ul>")
    details.append(f"<p><strong>Coverage</strong> {bool_badge(coverage['material'], 'material', 'not material')}</p>"
                   f'<div class="prose">{inline_markdown(coverage["note"])}</div><ul>{untouched}</ul>')
    if prior:
        details.append(f"<p><strong>Prior gaps: the Driver's answers and the Skeptic's judgment</strong></p><ul>{prior}</ul>")

    return f"""
    <div class="checkpoint">
      <h3>Checkpoint {checkpoint_num} {verdict_badge(skeptic['verdict'])}</h3>
      <p class="summary">{inline_markdown(hypothesis['summary'])}</p>
      <p class="skeptic-line"><strong>Skeptic:</strong> {inline_markdown(skeptic['verdict_reason'])}</p>
      {observations_html}
      {gaps_html}
      {_prior_gaps_line(hypothesis['prior_gaps'], skeptic['prior_gaps_check'])}
      <details class="fold">
        <summary>Details: evidence, coverage and prior gaps</summary>
        {''.join(details)}
      </details>
      {tests_fold}
    </div>
    """


def _render_rounds(rounds, render_test_entry) -> str:
    if not rounds:
        return '<p class="prose-muted">No rounds executed - the Driver gave up immediately at the start of this checkpoint.</p>'
    parts = []
    for round_num in sorted(rounds):
        entries = rounds[round_num]
        reasoning = entries[0].get("round_reasoning", "")
        tests_html = "".join(render_test_entry(e) for e in entries)
        parts.append(f"""
        <div class="round">
          <p class="eyebrow">Round {round_num}</p>
          <div class="prose reasoning-text">{render_prose(reasoning)}</div>
          <div class="test-grid">{tests_html}</div>
        </div>
        """)
    return "".join(parts)


def _render_casting_section(casting_log, checkpoints, render_test_entry) -> str:
    by_checkpoint = {}
    for entry in casting_log:
        by_checkpoint.setdefault(entry["checkpoint"], {}).setdefault(entry["round"], []).append(entry)

    checkpoint_by_num = {c["checkpoint"]: c for c in checkpoints}

    # A checkpoint whose Driver gives up on its first round proposes zero tests, so
    # it never contributes anything to casting_log - but it still gets a hypothesis
    # + Skeptic review. Iterating only over by_checkpoint's keys would silently drop
    # that checkpoint's conclusion entirely, even though it's real, generated data.
    all_checkpoint_nums = sorted(set(by_checkpoint) | set(checkpoint_by_num))
    return "".join(
        _render_checkpoint(n, checkpoint_by_num.get(n), by_checkpoint.get(n, {}), render_test_entry)
        for n in all_checkpoint_nums
    )


def _render_one_bug_report(bug_report) -> str:
    steps = "".join(f"<li>{inline_markdown(s)}</li>" for s in bug_report.get("steps_to_reproduce", []))
    severity = bug_report.get("severity")
    status = bug_report.get("status")
    return f"""
    <div class="exhibit exhibit-final">
      <h3>{esc(bug_report.get('title'))}</h3>
      <p>{badge(severity, 'bad' if severity == 'high' else 'warn')}
         {badge(status, 'good' if status == 'corroborated' else 'warn')}</p>
      <div class="prose">{render_prose(bug_report.get('description'))}</div>
      <p><strong>Steps to reproduce</strong></p>
      <ol>{steps}</ol>
      <p><strong>Expected behavior</strong></p>
      <div class="prose">{render_prose(bug_report.get('expected_behavior'))}</div>
      <p><strong>Actual behavior</strong></p>
      <div class="prose">{render_prose(bug_report.get('actual_behavior'))}</div>
      <div class="caveats">
        <p><strong>Caveats</strong></p>
        <div class="prose">{render_prose(bug_report.get('caveats'))}</div>
      </div>
    </div>
    """


_DIAGNOSTIC_TONES = {"stop": "bad", "warn": "warn", "info": "neutral"}


def _render_diagnostics_section(checkpoints) -> str:
    """The run's own findings about itself - see engine/diagnostics.py.

    Rendered from the LAST checkpoint's diagnostics rather than from all of them:
    each checkpoint's set is computed over the whole log up to that point, so the
    final one is a superset and printing every checkpoint's would repeat the same
    finding once per checkpoint with a rising test count.

    A section that renders nothing when there are no findings would be the wrong
    behaviour for the same reason the "unavailable" finding exists - so the absence
    of findings is stated rather than left blank, and it is only omitted entirely
    when there are no checkpoints at all to have findings about.
    """
    if not checkpoints:
        return ""
    findings = checkpoints[-1].get("diagnostics") or []
    if not findings:
        body = ('<p class="prose">No run-level findings: the executed tests started from a '
                'consistent state, the actions tried had observable effects, and every attempt '
                'to return to baseline worked.</p>')
    else:
        rows = []
        for finding in findings:
            tests = finding.get("tests") or []
            where = (f'<span class="prose-muted">tests {esc(", ".join(str(t) for t in tests))}</span>'
                     if tests else "")
            rows.append(f"""
            <article class="test">
              <div class="test-hypothesis">
                {badge(finding.get('severity', 'info'), _DIAGNOSTIC_TONES.get(finding.get('severity'), 'neutral'))}
                <span class="test-number">{esc(finding.get('code'))}</span>
                <strong>{esc(finding.get('headline'))}</strong> {where}
              </div>
              <div class="test-outcome">{inline_markdown(finding.get('detail'))}</div>
            </article>
            """)
        body = "".join(rows)
    return f"""
    <section id="diagnostics">
      <p class="eyebrow">The run, not the SUT</p>
      <h2>Run diagnostics</h2>
      <p class="prose">Computed arithmetically from what the executed tests actually did, with no
      model involved and nothing here specific to this system. These qualify the findings above
      them: an action that was never accepted cannot have demonstrated anything about what it
      does, and a test that did not start from the baseline was not the test it was cast as.</p>
      {body}
    </section>
    """


def _render_conclusion_section(observations) -> str:
    """Every observation of the final checkpoint with the status the engine gave
    it. Bugs also get a written report below; findings and anomalies are complete
    here."""
    if not observations:
        return ""
    rows = "".join(f"""
        <li>
          <span class="idtag">{esc(o['id'])}</span> {esc(o['kind'])} ({esc(o['severity'])})
          {badge(o['status'], 'good' if o['status'] == 'corroborated' else 'warn')}
          {inline_markdown(o['claim'])} {_tests_label(o['tests'])}{_lowered_label(o)}
          <div class="prose-muted">{inline_markdown(o['skeptic_note'])}</div>
        </li>
        """ for o in observations)
    return f"""
    <section id="conclusion">
      <p class="eyebrow">Final checkpoint conclusion</p>
      <h2>Findings, anomalies and bugs</h2>
      <ul>{rows}</ul>
    </section>
    """


def _render_bug_report_section(bug_reports) -> str:
    if not bug_reports:
        return ""
    heading = "Bug report" if len(bug_reports) == 1 else f"Bug reports ({len(bug_reports)})"
    reports_html = "".join(_render_one_bug_report(b) for b in bug_reports)
    return f"""
    <section id="bug-report">
      <p class="eyebrow">Written up for the bugs</p>
      <h2>{heading}</h2>
      {reports_html}
    </section>
    """


CSS = """
:root {
  --ink: #17262b;
  --ink-soft: #45575d;
  --paper: #eef2f0;
  --panel: #ffffff;
  --line: rgba(23, 38, 43, 0.14);
  --accent: #0e6e76;
  --good-bg: #dcece1; --good-fg: #205c33;
  --bad-bg: #f6dcd8;  --bad-fg: #8c2c22;
  --warn-bg: #f1e6cd; --warn-fg: #7a5510;
  --code-bg: #17262b; --code-fg: #d9e6e3;
  --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --font-body: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "SF Mono", "Cascadia Code", "Roboto Mono", Consolas, monospace;
}

* { box-sizing: border-box; }

body {
  font-family: var(--font-body);
  background: var(--paper);
  color: var(--ink);
  margin: 0;
  line-height: 1.55;
  font-variant-numeric: tabular-nums;
}

.wrap { max-width: 880px; margin: 0 auto; padding: 0 1.5rem 4rem; }

.topbar {
  position: sticky; top: 0; z-index: 10;
  background: rgba(238, 242, 240, 0.92);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--line);
}
.topbar-inner {
  max-width: 880px; margin: 0 auto; padding: 0.85rem 1.5rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  flex-wrap: wrap;
}
.topbar-title { font-family: var(--font-display); font-size: 1.05rem; font-weight: 600; }
.topbar-nav { display: flex; gap: 1.25rem; list-style: none; margin: 0; padding: 0; font-size: 0.85rem; }
.topbar-nav a {
  color: var(--ink-soft); text-decoration: none; border-bottom: 1px solid transparent;
}
.topbar-nav a:hover, .topbar-nav a:focus-visible {
  color: var(--accent); border-bottom-color: var(--accent);
}
@media (prefers-reduced-motion: no-preference) {
  .topbar-nav a { transition: color 120ms ease, border-color 120ms ease; }
}

.hero { padding: 3rem 0 1.5rem; }
.hero h1 {
  font-family: var(--font-display); font-size: 2.1rem; font-weight: 600;
  margin: 0.3rem 0 1rem; text-wrap: balance;
}
.hero .eyebrow { margin-bottom: 0; }
.stat-row {
  display: flex; flex-wrap: wrap; gap: 1.75rem; padding: 1rem 1.25rem;
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
}
.stat { display: flex; flex-direction: column; gap: 0.15rem; }
.stat .num { font-family: var(--font-mono); font-size: 1.3rem; font-weight: 600; }
.stat .label { font-size: 0.75rem; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.05em; }

.eyebrow {
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent); font-weight: 600; margin: 0 0 0.4rem;
}

section { margin-top: 3rem; }
h2 { font-family: var(--font-display); font-size: 1.5rem; margin: 0 0 1.25rem; text-wrap: balance; }
h3 { font-family: var(--font-display); font-size: 1.2rem; margin: 1.5rem 0 0.5rem; }
h4 { font-size: 1rem; margin: 1.25rem 0 0.4rem; }

.checkpoint { margin: 1.75rem 0; }
.round { margin: 1.25rem 0 1.75rem; }

.checkpoint {
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 1rem 1.5rem 1.25rem;
}
.checkpoint h3 { margin-top: 0.25rem; }
.checkpoint .summary { font-size: 1.02rem; margin: 0.25rem 0 0.4rem; }
.checkpoint .skeptic-line { font-size: 0.94rem; color: var(--ink-soft); margin: 0 0 0.75rem; }
.line-list { margin: 0.4rem 0 0.9rem; padding-left: 1.1rem; font-size: 0.92rem; }
.line-list li { margin: 0.35rem 0; }
.idtag {
  font-family: var(--font-mono); font-size: 0.78rem; color: var(--ink-soft);
  background: var(--paper); border: 1px solid var(--line); border-radius: 4px; padding: 0 0.35rem;
}

details.fold { margin: 0.6rem 0 0; border-top: 1px solid var(--line); padding-top: 0.6rem; }
details.fold summary {
  cursor: pointer; font-size: 0.8rem; color: var(--ink-soft);
  text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600;
}
details.fold summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
details.fold[open] summary { margin-bottom: 0.6rem; }
details.fold ul { font-size: 0.9rem; padding-left: 1.1rem; }
.reasoning-text {
  color: var(--ink-soft); margin: 0.2rem 0 0.8rem;
  border-left: 2px solid var(--line); padding-left: 0.85rem;
}

.test-grid { display: flex; flex-direction: column; gap: 0.6rem; }
.test {
  background: var(--panel); border: 1px solid var(--line); border-radius: 4px;
  padding: 0.85rem 1rem;
}
.test-hypothesis { font-size: 0.92rem; margin-bottom: 0.5rem; }
.account-list { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.oracle-heuristic {
  background: var(--paper); border: 1px solid var(--line); border-radius: 4px;
  padding: 0.75rem 1rem; margin: 0.75rem 0;
}
.oracle-heuristic h4 { margin: 0 0 0.4rem; }
.vector-list { margin: 0.4rem 0; padding-left: 1.2rem; }
.vector-list li { margin: 0.35rem 0; font-size: 0.88rem; }
.test-number {
  font-family: var(--font-mono); font-size: 0.72rem; color: var(--ink-soft);
  background: var(--paper); border: 1px solid var(--line); border-radius: 4px;
  padding: 0.05rem 0.4rem; margin-right: 0.5rem;
}
.probe-label { font-style: italic; color: var(--ink-soft); }
.payload, .schema-doc {
  font-family: var(--font-mono); font-size: 0.82rem; background: var(--code-bg);
  color: var(--code-fg); border-radius: 4px; padding: 0.6rem 0.75rem; margin: 0.4rem 0;
  white-space: pre-wrap; word-break: break-word; overflow-x: auto;
}
.test-predicted, .test-outcome { font-size: 0.88rem; margin-top: 0.35rem; }
.sep { color: var(--line); margin: 0 0.15rem; }

.exhibit {
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 1.25rem 1.5rem; margin: 1.25rem 0;
}
.exhibit-final { border-color: var(--accent); border-width: 1px; }

.prose { font-size: 0.94rem; }
.prose p { margin: 0.6rem 0; }
.prose p:first-child { margin-top: 0; }
.prose p:last-child { margin-bottom: 0; }
.prose h4, .prose h5, .prose h6 {
  font-family: var(--font-body); text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--ink-soft); font-size: 0.78rem; margin: 1rem 0 0.35rem;
}
.prose ul { margin: 0.4rem 0; padding-left: 1.2rem; }
.prose li { margin: 0.2rem 0; }
.prose code {
  font-family: var(--font-mono); font-size: 0.85em; background: var(--paper);
  border: 1px solid var(--line); border-radius: 3px; padding: 0.05rem 0.3rem;
}
.prose-muted { color: var(--ink-soft); font-size: 0.92rem; }
.caveats {
  margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--line);
  font-size: 0.92rem; color: var(--ink-soft);
}

.badge {
  display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px;
  font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em;
}
.badge-good { background: var(--good-bg); color: var(--good-fg); }
.badge-bad { background: var(--bad-bg); color: var(--bad-fg); }
.badge-warn { background: var(--warn-bg); color: var(--warn-fg); }
/* For an outcome that is neither good nor bad nor worth flagging - "nothing
   happened" is a legitimate, expected result for some SUTs, and rendering it in
   warning colours would read as a problem. Without this class such a badge falls
   back to `.badge` alone: a pill with no background at all. */
.badge-neutral { background: var(--line); color: var(--ink-soft); }

a:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
"""


def _stat(value, label) -> str:
    return f'<div class="stat"><span class="num">{esc(value)}</span><span class="label">{esc(label)}</span></div>'


def render_report(output: dict, bug_reports: list | None, adapter: SUTAdapter) -> str:
    bug_reports = bug_reports or []
    api_schema = output.get("api_schema", "")
    onboarding_extra = output.get("onboarding_extra", {})
    happy_day_example = output.get("happy_day_example", {})
    casting_log = output.get("casting_log", [])
    checkpoints = output.get("checkpoints", [])
    observations = output.get("observations", [])
    checkpoints_run = len({e["checkpoint"] for e in casting_log} | {c["checkpoint"] for c in checkpoints})

    if output.get("error"):
        eyebrow, title = "Run incomplete", "Stopped early"
        stats = [_stat(output["error"][:40] + ("..." if len(output["error"]) > 40 else ""), "reason")]
    elif observations:
        counts = {kind: sum(1 for o in observations if o["kind"] == kind) for kind in ("bug", "anomaly", "finding")}
        eyebrow = ", ".join(f"{n} {kind}{'' if n == 1 else 's'}" for kind, n in counts.items() if n)
        title = bug_reports[0]["title"] if len(bug_reports) == 1 else observations[0]["claim"]
        stats = [
            _stat(checkpoints_run, "checkpoints run"),
            _stat(len(casting_log), "tests executed"),
            _stat(sum(1 for o in observations if o["status"] == "corroborated"), "corroborated"),
        ]
    else:
        reason = output.get("stopped_reason", "unknown")
        eyebrow, title = "Checkpoints concluded", "Nothing looked wrong"
        stats = [
            _stat(checkpoints_run, "checkpoints run"),
            _stat(len(casting_log), "tests executed"),
            _stat(reason.replace("_", " "), "stopped because"),
        ]

    nav_items = [("#schema", "Schema")]
    if casting_log or checkpoints:
        nav_items.append(("#casting", "Checkpoints"))
    if checkpoints:
        nav_items.append(("#diagnostics", "Diagnostics"))
    if observations:
        nav_items.append(("#conclusion", "Conclusion"))
    if bug_reports:
        nav_items.append(("#bug-report", "Bug report"))
    nav_html = "".join(f'<li><a href="{href}">{label}</a></li>' for href, label in nav_items)

    report_title = adapter.report_title or f"{adapter.display_name} Investigation Report"
    onboarding_html = adapter.render_onboarding_section(api_schema, onboarding_extra, happy_day_example)
    casting_html = _render_casting_section(casting_log, checkpoints, adapter.render_test_entry)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(report_title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <span class="topbar-title">{esc(adapter.display_name)} Report</span>
    <ul class="topbar-nav">{nav_html}</ul>
  </div>
</div>

<div class="wrap">
  <div class="hero">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{esc(title)}</h1>
    <div class="stat-row">{''.join(stats)}</div>
  </div>

  <section id="schema">
    <p class="eyebrow">Onboarding</p>
    <h2>Schema &amp; happy-day example</h2>
    {onboarding_html}
  </section>

  <section id="casting">
    <p class="eyebrow">Checkpoint loop</p>
    <h2>Checkpoints</h2>
    {casting_html}
  </section>

  {_render_diagnostics_section(checkpoints)}

  {_render_conclusion_section(observations)}

  {_render_bug_report_section(bug_reports)}
</div>
</body>
</html>
"""


def render_report_from_dir(results_dir: Path, adapter: SUTAdapter) -> str:
    output = json.loads((results_dir / "output.json").read_text(encoding="utf-8"))
    bugs_path = results_dir / "bugs.json"
    bug_reports = json.loads(bugs_path.read_text(encoding="utf-8")) if bugs_path.exists() else []
    return render_report(output, bug_reports, adapter)
