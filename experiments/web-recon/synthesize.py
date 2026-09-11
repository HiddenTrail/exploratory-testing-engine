"""Optional, batched LLM synthesis over a finished ontology - the one place a model is
used, and it is off by default.

It never touches the crawl: it runs *after*, on the recorded ontology, and only when the
caller asks (`wiki.py --llm`). One tool-forced call turns the deterministic map + findings
into a few falsifiable claims about what the app is and where it is weak - under the
kit's citation rule: every claim must cite a specific measurement from the digest, carry
a measured / inferred / speculative marker, and name the rival explanation it would lose
to. General knowledge about the app that the digest does not support is inadmissible.

Authentication is the engine's (`ENGINE_USE_BEDROCK` etc.), reused so this PoC does not
grow its own. The digest-building, validation and rendering are pure and unit-tested with
a fake client; the real call is exercised only behind the flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.client import build_client, call_tool_with_retry, default_model  # noqa: E402

_CONFIDENCE = ("measured", "inferred", "speculative")

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Summarise the app and list falsifiable claims, each grounded in a cited measurement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One or two sentences: what this app appears to be."},
            "claims": {
                "type": "array",
                "description": "Falsifiable claims about purpose, behaviour, or weaknesses.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "cites": {"type": "string", "description": "The specific measurement from the digest this rests on."},
                        "confidence": {"type": "string", "enum": list(_CONFIDENCE)},
                        "rival": {"type": "string", "description": "The alternative explanation this claim would lose to."},
                    },
                    "required": ["claim", "cites", "confidence", "rival"],
                },
            },
        },
        "required": ["summary", "claims"],
    },
}

SYSTEM = """You are reviewing an automated read-only exploration of a web app. You are given a
digest of what the crawl actually measured - its states (views), the transitions between them,
the functional findings (HTTP/console errors), and the structural observations (dead controls,
dead ends, redundant controls).

Write a short summary of what the app appears to be, then a few falsifiable claims about its
purpose, behaviour, or weaknesses. Every claim MUST cite a specific measurement from the digest
(name the state, transition, or finding), carry a confidence marker - "measured" (the digest
states it directly), "inferred" (a reasonable deduction from it), or "speculative" (a guess) -
and name the rival explanation it would lose to. Do NOT use general knowledge about the app that
the digest does not support; a claim that cites nothing does not belong.

Call submit_review with your answer."""


def digest(onto) -> str:
    """A compact, model-readable summary of the ontology - only what was measured."""
    lines = [f"APP: {onto.target.get('url', '?')}",
             f"{len(onto.states)} states, {len(onto.transitions)} transitions, "
             f"{len(onto.findings)} functional findings, {len(onto.observations)} structural observations",
             "", "STATES:"]
    for s in onto.states:
        lines.append(f"  {s.id}: signature={s.signature}  title={s.title!r}")
    lines.append("\nTRANSITIONS:")
    for t in onto.transitions:
        lines.append(f"  {t.source} --{t.action.kind} {t.action.element_key} ({t.effect})--> {t.dest}")
    lines.append("\nFUNCTIONAL FINDINGS:")
    lines += [f"  [{f.kind}] {f.summary}" for f in onto.findings] or ["  (none)"]
    lines.append("\nSTRUCTURAL OBSERVATIONS:")
    lines += [f"  [{o.kind}] {o.summary}" for o in onto.observations] or ["  (none)"]
    return "\n".join(lines)


def validate_review(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    if not isinstance(data.get("summary"), str) or not data["summary"]:
        errors.append("'summary' must be a non-empty string")
    claims = data.get("claims")
    if not isinstance(claims, list):
        errors.append("'claims' must be a list")
    else:
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                errors.append(f"claims[{i}] must be an object")
                continue
            for key in ("claim", "cites", "rival"):
                if not isinstance(c.get(key), str) or not c[key]:
                    errors.append(f"claims[{i}].{key} must be a non-empty string")
            if c.get("confidence") not in _CONFIDENCE:
                errors.append(f"claims[{i}].confidence must be one of {_CONFIDENCE}")
    return errors


def synthesize(onto, client, model: str, max_tokens: int = 1500) -> dict:
    """One tool-forced review call. Pure of I/O beyond the client, so it is testable with
    a fake client."""
    return call_tool_with_retry(
        client, model=model, system=SYSTEM, tools=[REVIEW_TOOL],
        tool_name="submit_review", user_message=digest(onto),
        validate_fn=validate_review, max_tokens=max_tokens)


def render_synthesis(review: dict) -> str:
    """The review as an HTML section. Pure - no model, no I/O."""
    import html as _html
    esc = lambda x: _html.escape(str(x if x is not None else ""))
    colours = {"measured": "#16a34a", "inferred": "#d97706", "speculative": "#dc2626"}
    rows = "".join(
        f'<tr><td>{esc(c.get("claim"))}</td>'
        f'<td><span class="badge" style="background:{colours.get(c.get("confidence"), "#64748b")}">'
        f'{esc(c.get("confidence"))}</span></td>'
        f'<td class="loc">{esc(c.get("cites"))}</td><td>{esc(c.get("rival"))}</td></tr>'
        for c in review.get("claims", []))
    return (f'<p>{esc(review.get("summary"))}</p>'
            f'<table class="findings"><thead><tr><th>claim</th><th>confidence</th>'
            f'<th>cites</th><th>would lose to</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<p class="eyebrow">Model synthesis — every claim cites a measurement; '
            f'read the deterministic sections above as the record.</p>')


def run_synthesis(onto) -> str:
    """Build the client (engine auth), synthesise, render. Soft-fails to a note so a
    missing key / model never breaks the wiki - the deterministic wiki is already whole."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO_ROOT / ".env")  # the Bedrock config (ENGINE_USE_BEDROCK, AWS_*) lives here
        review = synthesize(onto, build_client(), default_model())
        return render_synthesis(review)
    # SystemExit (build_client raises it on a missing key/region) is a BaseException, not
    # an Exception, so it must be named explicitly or a misconfigured --llm would abort
    # the whole wiki instead of soft-failing to this note.
    except (Exception, SystemExit) as e:  # noqa: BLE001 - a synthesis failure must never break the wiki
        return f'<p class="ok">(model synthesis unavailable: {type(e).__name__}: {e})</p>'
