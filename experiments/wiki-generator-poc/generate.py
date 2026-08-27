"""Wiki Generator PoC: proves the mechanics of `.claude/commands/wiki-ingest.md`
as real, testable code instead of only an interactive Claude Code prompt -
generate a product wiki (per AGENTS.md's OKF-flavored page types) from a
directory of raw, product-facing files.

Two LLM passes per run, both tool-forced (same call->validate->retry shape
every experiment's run_live.py uses):
  1. One "summarize" call per file under --source -> wiki/summaries/<slug>.md
  2. One "synthesize" call across all summaries just produced ->
     wiki/concepts/<product>-product-model.md

Deliberately narrow, matching how this repo's other PoCs scope down before
graduating to engine/: no entity pages, no recursive source directories, no
in-scope/out-of-scope classification (the caller is trusted to only point
--source at a directory that's already product-facing raw material - see
AGENTS.md's "What counts as a raw source" for what that means in practice).
Rendering (frontmatter + body markdown) is done in Python from the tool call's
structured output, not by asking the model to emit raw markdown - same
"structured call, deterministic render" split as engine/report.py.

results/wiki/ in this experiment is the proof run's output, committed like
oracle-agent-poc's results/oracle_library.json.

Run:
  pip install -r requirements.txt
  cp .env.example .env   # fill in ANTHROPIC_API_KEY
  python generate.py [--source raw] [--dest results/wiki] [--product token_purchase]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3
HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent

SUMMARY_TOOL = {
    "name": "submit_source_summary",
    "description": "Report a faithful digest of the one raw source given, structured as an OKF Source Summary page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Human title for this page, e.g. 'PROJ-101 — Exploratory testing needed'."},
            "description": {"type": "string", "description": "ONE sentence - what this source is and covers."},
            "key_points": {
                "type": "array", "items": {"type": "string"},
                "description": "Faithful facts/claims the source actually states. No invention, no interpretation it doesn't support.",
            },
            "decisions_and_commitments": {
                "type": "array", "items": {"type": "string"},
                "description": "Any decisions, commitments, or fixed rules the source states. Empty list if none.",
            },
            "risks_and_open_questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Anything the source flags as unknown, risky, or undocumented. Empty list if none.",
            },
        },
        "required": ["title", "description", "key_points", "decisions_and_commitments", "risks_and_open_questions"],
    },
}

SYNTHESIS_TOOL = {
    "name": "submit_product_model",
    "description": "Report a product model synthesized across multiple source summaries, structured as an OKF Quality Concept page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string", "description": "ONE sentence describing this product model page."},
            "what_it_is": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}, "description": "Which given source ids support this statement."},
                    },
                    "required": ["text", "source_ids"],
                },
                "description": "What the product fundamentally is/does, drawn from across the sources.",
            },
            "current_state_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "source_ids"],
                },
                "description": "Findings that only emerge from combining >=1 sources - agreements, gaps between them, or what neither source alone tells you.",
            },
            "open_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "source_ids"],
                },
                "description": "What's still unknown about the product after reading all sources together.",
            },
        },
        "required": ["title", "description", "what_it_is", "current_state_findings", "open_questions"],
    },
}


def call_tool_with_retry(client, *, system, tools, tool_name, user_message, max_tokens, validate_fn):
    messages = [{"role": "user", "content": user_message}]
    last_errors = ["no attempts made"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system, tools=tools,
            tool_choice={"type": "tool", "name": tool_name}, messages=messages,
        )
        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            last_errors = [f"no tool_use block (stop_reason={message.stop_reason})"]
            print(f"  attempt {attempt} produced no tool call - retrying")
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call the tool. Try again."})
            continue

        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input

        last_errors = errors
        print(f"  attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": "Invalid: " + "; ".join(errors) + ". Fix and call the tool again with a corrected, complete answer.",
                "is_error": True,
            }],
        })

    raise RuntimeError(f"Gave up after {MAX_ATTEMPTS} attempts, last errors: {last_errors}")


def validate_summary(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    for field in ("title", "description"):
        if not isinstance(data.get(field), str) or not data[field]:
            errors.append(f"'{field}' must be a non-empty string")
    for field in ("key_points", "decisions_and_commitments", "risks_and_open_questions"):
        if not isinstance(data.get(field), list) or not all(isinstance(x, str) for x in data.get(field, [])):
            errors.append(f"'{field}' must be a list of strings")
    return errors


def validate_synthesis(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    for field in ("title", "description"):
        if not isinstance(data.get(field), str) or not data[field]:
            errors.append(f"'{field}' must be a non-empty string")
    for field in ("what_it_is", "current_state_findings", "open_questions"):
        items = data.get(field)
        if not isinstance(items, list):
            errors.append(f"'{field}' must be a list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]:
                errors.append(f"{field}[{i}].text must be a non-empty string")
            if not isinstance(item.get("source_ids"), list):
                errors.append(f"{field}[{i}].source_ids must be a list")
    return errors


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_user() -> str:
    try:
        name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=True).stdout.strip()
        return slugify(name) if name else "<your-id>"
    except Exception:
        return "<your-id>"


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_summary_page(product: str, src_id: str, src_path: Path, data: dict, author: str, timestamp: str) -> str:
    def bullets(items):
        return "\n".join(f"- {text}[^{src_id}]" for text in items) or "_none noted_"

    return f"""---
type: Source Summary
title: "{data['title']}"
description: {data['description']}
tags: [{product}]
status: draft
generated: {{ by: human:{author}, at: "{timestamp}" }}
sources:
  - id: {src_id}
    resource: {repo_relative(src_path)}
    title: "{src_path.name}"
---

# {data['title']}

## Key points

{bullets(data['key_points'])}

## Decisions & commitments

{bullets(data['decisions_and_commitments'])}

## Risks & open questions

{bullets(data['risks_and_open_questions'])}

[^{src_id}]: {repo_relative(src_path)}
"""


def render_concept_page(product: str, data: dict, sources: dict[str, Path], author: str, timestamp: str) -> str:
    def bullets(items):
        lines = []
        for item in items:
            marks = "".join(f"[^{sid}]" for sid in item["source_ids"] if sid in sources)
            lines.append(f"- {item['text']}{marks}")
        return "\n".join(lines) or "_none noted_"

    sources_yaml = "\n".join(
        f'  - id: {sid}\n    resource: {repo_relative(p)}\n    title: "{p.name}"' for sid, p in sources.items()
    )
    footnotes = "\n".join(f"[^{sid}]: {repo_relative(p)}" for sid, p in sources.items())

    return f"""---
type: Quality Concept
title: "{data['title']}"
description: {data['description']}
tags: [{product}, product-model]
status: draft
generated: {{ by: human:{author}, at: "{timestamp}" }}
sources:
{sources_yaml}
---

# {data['title']}

## What it is

{bullets(data['what_it_is'])}

## Current state / findings

{bullets(data['current_state_findings'])}

## Risks & open questions

{bullets(data['open_questions'])}

{footnotes}
"""


def ensure_workspace(dest: Path) -> None:
    for sub in ("summaries", "entities", "concepts", "log"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    config_path = dest.parent / "qpf.config.yml"
    if not config_path.exists():
        config_path.write_text(f'qpf:\n  customer: "{dest.parent.name}"\n  language: en\n', encoding="utf-8")


def rebuild_index(dest: Path) -> None:
    script = REPO_ROOT / ".wiki-source" / "scripts" / "rebuild-index.mjs"
    if not script.exists():
        print(f"! {script} not found - skipping index rebuild")
        return
    try:
        result = subprocess.run(
            ["node", str(script), "--dir", str(dest.parent)],
            capture_output=True, text=True, check=False,
        )
        print(result.stdout.strip())
        if result.returncode != 0:
            print(result.stderr.strip())
    except FileNotFoundError:
        print("! node not found on PATH - skipping index rebuild")


def append_log(dest: Path, product: str, entries: list[str], author: str, timestamp: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = dest / "log" / f"{today}.md"
    if not log_path.exists():
        log_path.write_text(
            f"""---
type: Log Entry
title: "Log — {today}"
description: Operations run against this workspace on {today}.
generated: {{ by: human:{author}, at: "{timestamp}" }}
---

# Log — {today}

""",
            encoding="utf-8",
        )
    with log_path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(f"- {entry}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="raw", help="Directory of raw, product-facing files to ingest (default: raw)")
    parser.add_argument("--dest", default="results/wiki", help="Destination wiki directory (default: results/wiki)")
    parser.add_argument("--product", default=None, help="Product/SUT slug, used as a filename prefix (default: inferred from --dest's parent dir name)")
    args = parser.parse_args()

    load_dotenv(HERE / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    source_dir = (HERE / args.source).resolve()
    dest_dir = (HERE / args.dest).resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"--source '{source_dir}' is not a directory")
    product = args.product or dest_dir.parent.name

    files = sorted(p for p in source_dir.iterdir() if p.is_file())
    if not files:
        raise SystemExit(f"No files found under {source_dir}")

    ensure_workspace(dest_dir)
    author = git_user()
    timestamp = now_iso()
    log_entries = []
    sources: dict[str, Path] = {}
    summaries: list[tuple[str, dict]] = []

    for path in files:
        src_id = slugify(path.stem)
        print(f"Summarizing {path.name} (id={src_id})...")
        text = path.read_text(encoding="utf-8")
        result = call_tool_with_retry(
            client,
            system=(
                "You are digesting ONE raw source (a product spec, ticket, or similar) into a faithful "
                "Source Summary. Capture only what the source actually states - no invented facts, no "
                "interpretation it doesn't support. Call submit_source_summary with your answer."
            ),
            tools=[SUMMARY_TOOL],
            tool_name="submit_source_summary",
            user_message=text,
            max_tokens=1536,
            validate_fn=validate_summary,
        )
        page = render_summary_page(product, src_id, path, result, author, timestamp)
        out_name = f"{slugify(product)}-{src_id}.md"
        (dest_dir / "summaries" / out_name).write_text(page, encoding="utf-8")
        print(f"  -> wiki/summaries/{out_name}")
        log_entries.append(f"**Ingest**: `{repo_relative(path)}` -> `wiki/summaries/{out_name}`")
        sources[src_id] = path
        summaries.append((src_id, result))

    print("Synthesizing product model across all summaries...")
    combined = "\n\n---\n\n".join(
        f"Source id: {sid}\nTitle: {data['title']}\nKey points:\n" + "\n".join(f"- {p}" for p in data["key_points"])
        for sid, data in summaries
    )
    synthesis = call_tool_with_retry(
        client,
        system=(
            f"You are synthesizing a product model for '{product}' across multiple already-digested source "
            "summaries (given as the user message, one per source id). Find what emerges from combining them - "
            "agreements, gaps, or what neither tells you alone - not a re-listing of either summary alone. Tag "
            "each statement with the source_ids that actually support it. Call submit_product_model with your answer."
        ),
        tools=[SYNTHESIS_TOOL],
        tool_name="submit_product_model",
        user_message=combined,
        max_tokens=2048,
        validate_fn=validate_synthesis,
    )
    concept_page = render_concept_page(product, synthesis, sources, author, timestamp)
    concept_name = f"{slugify(product)}-product-model.md"
    (dest_dir / "concepts" / concept_name).write_text(concept_page, encoding="utf-8")
    print(f"  -> wiki/concepts/{concept_name}")
    log_entries.append(f"**Synthesize**: {', '.join(sid for sid, _ in summaries)} -> `wiki/concepts/{concept_name}`")

    rebuild_index(dest_dir)
    log_entries.append(f"**Rebuild**: `node .wiki-source/scripts/rebuild-index.mjs --dir {repo_relative(dest_dir.parent)}` -> `wiki/index.md`")
    append_log(dest_dir, product, log_entries, author, timestamp)
    print(f"\nDone. Wiki written to {dest_dir}")


if __name__ == "__main__":
    main()
