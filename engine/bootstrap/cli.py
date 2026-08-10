"""CLI entrypoint chaining all 4 adapter-bootstrap phases end-to-end:
python -m engine.bootstrap.cli --name <slug> --display-name <Name> --base-url <url>
[--spec-text <text>] [--max-probes N]

Writes a draft adapter under engine/adapters/<name>/ and prints the registry
line to add plus the run command - it deliberately does NOT edit
engine/adapters/registry.py itself. Registering (and thus running) a
generated adapter is the last explicit human gate before it goes live,
matching the "human review before trust" principle used throughout this
roadmap.

--discover-only stops after Phase 1 (OpenAPI/Swagger discovery) and writes
just that result to runs/<name>/discovered_schema.json and
discovered_schema.html - no LLM calls at all, so it's a free way to check
what a SUT publishes before spending any probing/generation budget on it.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine.bootstrap.discovery import discover_schema
from engine.bootstrap.generate import generate_adapter_source, write_adapter_module
from engine.bootstrap.probe import run_bootstrap_probe_loop
from engine.bootstrap.report import render_discovery_report
from engine.bootstrap.schema import discover_or_draft_schema
from engine.client import build_client

_ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"
_RUNS_DIR = Path("runs")


def _run_discover_only(base_url: str, name: str) -> None:
    print(f"Discovering OpenAPI/Swagger schema at {base_url} ...")
    schema = discover_schema(base_url)
    fetched_note = f" (fetched from {schema.fetched_from})" if schema.fetched_from else ""
    print(f"    status: {schema.status}{fetched_note}")

    for endpoint in schema.endpoints:
        print(f"\n{endpoint.method} {endpoint.path}")
        for field in endpoint.request_fields:
            req = "required" if field.required else "optional"
            enum_note = f" (one of {field.enum})" if field.enum else ""
            print(f"  {field.name}: {field.type}{enum_note} - {req}")

    out_dir = _RUNS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "discovered_schema.json"
    json_path.write_text(json.dumps(dataclasses.asdict(schema), indent=2), encoding="utf-8")
    html_path = out_dir / "discovered_schema.html"
    html_path.write_text(render_discovery_report(schema, base_url), encoding="utf-8")
    print(f"\nWrote discovered schema to {json_path} and {html_path}")

    if not schema.endpoints:
        detail = f" - {schema.error}" if schema.error else ""
        raise SystemExit(f"No OpenAPI/Swagger schema found (status: {schema.status}){detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a draft SUTAdapter from a live API, end to end.")
    parser.add_argument("--name", required=True, help="Adapter slug, e.g. 'my_api' (used as the module/package name).")
    parser.add_argument("--display-name", default=None, dest="display_name")
    parser.add_argument("--base-url", required=True, dest="base_url")
    parser.add_argument("--spec-text", default=None, dest="spec_text",
                         help="Free-text API description, used only if schema discovery finds nothing.")
    parser.add_argument("--max-probes", type=int, default=8, dest="max_probes")
    parser.add_argument(
        "--discover-only", action="store_true", dest="discover_only",
        help="Only run OpenAPI/Swagger discovery (Phase 1, no LLM calls) and write the result to "
             "runs/<name>/discovered_schema.json, then exit - skips probing and generation.",
    )
    args = parser.parse_args()

    import keyword
    if not args.name.isidentifier() or keyword.iskeyword(args.name):
        raise SystemExit("--name must be a valid Python identifier (not a keyword), e.g. 'my_api'")

    if args.discover_only:
        _run_discover_only(args.base_url, args.name)
        return

    if args.display_name is None:
        raise SystemExit("--display-name is required unless --discover-only is set")

    anthropic_client = build_client()

    print(f"[1/3] Discovering schema at {args.base_url} ...")
    schema = discover_or_draft_schema(args.base_url, args.spec_text, anthropic_client)
    if not schema.endpoints:
        raise SystemExit(
            f"No usable schema found or drafted (status: {schema.status}). "
            "Nothing to probe - try passing --spec-text, or check the base URL."
        )
    print(f"    schema source: {schema.source}, endpoint: {schema.endpoints[0].method} {schema.endpoints[0].path}")

    print(f"[2/3] Probing live SUT to confirm the schema (up to {args.max_probes} probes) ...")
    bootstrap_result = run_bootstrap_probe_loop(anthropic_client, args.base_url, schema, max_probes=args.max_probes)
    print(f"    bootstrap status: {bootstrap_result.status}")

    if bootstrap_result.status == "failed":
        raise SystemExit(
            f"Bootstrap probing never got a working example - nothing real to generate an adapter around.\n"
            f"Reasoning from the last review: {bootstrap_result.notes or '(none recorded)'}"
        )

    print("[3/3] Generating draft adapter ...")
    source = generate_adapter_source(args.name, args.display_name, args.base_url, bootstrap_result)
    adapter_path = write_adapter_module(_ADAPTERS_DIR, args.name, source)

    print(f"\nDraft adapter written to {adapter_path}")
    if bootstrap_result.status == "inconclusive":
        print("NOTE: bootstrap was inconclusive - review the warning comment at the top of the file before trusting it.")
    print("\nTo register it, add this line to engine/adapters/registry.py's _ADAPTERS dict:")
    print(f'    "{args.name}": "engine.adapters.{args.name}.adapter",')
    print(f"\nThen run it with:\n    python -m engine.cli --adapter {args.name}")


if __name__ == "__main__":
    main()
