"""Phase 2 of the Playwright-MCP GUI PoC: a Driver that proposes test
scenarios against the mock GUI, then actually carries each one out in a
real browser via Playwright MCP tools.

Deliberately excludes hypothesis formation and the Skeptic - both already
work fine elsewhere in this project with different evidence shapes, so
they're not at risk. The one genuinely unproven thing here is whether an
LLM can meaningfully perceive-decide-act its way through a browser via
MCP tools at all - this script exists to answer exactly that question,
nothing more.

Scenario proposal ("casting") is a single tool-forced call - the same
low-risk pattern every other experiment's run_live.py uses. Carrying out
a scenario is the new mechanism: a real multi-turn agentic loop, since
(unlike an HTTP request) a browser action can't be fully specified in
advance - what you can click next depends on what actually rendered after
the last click.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Authenticate the same way as the rest of the repo: the engine picks the direct
# Anthropic API or Bedrock from ENGINE_USE_BEDROCK, and returns the right model id for
# whichever it built (Bedrock's Messages endpoint does not carry the direct-API model).
# Reused rather than duplicated so this PoC cannot drift from how the engine authenticates.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from engine.client import build_client, default_model  # noqa: E402

# Model-generated text can contain non-ASCII characters that the default
# Windows console codec can't encode, crashing a plain print().
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_ATTEMPTS = 3
MAX_SCENARIO_TURNS = 10
NUM_SCENARIOS = 2

FRONTEND_URL = "http://localhost:5173"
BACKEND_DOCS_URL = "http://127.0.0.1:8010/docs"

# Bare "npx" isn't directly spawnable as a subprocess on Windows - only the
# .cmd shim actually exists as a runnable file there. Confirmed via a live
# spike before writing this loop.
NPX_CMD = "npx.cmd" if sys.platform == "win32" else "npx"


def call_tool_with_retry(client, *, model, system, tools, tool_name, user_message, max_tokens, validate_fn):
    """Same call->validate->retry shape every experiment's run_live.py
    uses - retries feed the model's own malformed call and the concrete
    validation errors back as a tool_result, so a systematic
    misunderstanding has a chance to self-correct."""
    messages = [{"role": "user", "content": user_message}]
    last_errors = ["no attempts made"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, tools=tools,
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


CASTING_TOOL = {
    "name": "submit_test_scenarios",
    "description": f"Propose exactly {NUM_SCENARIOS} test scenarios to try against the live GUI.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string", "description": "Your reasoning for these scenario choices."},
            "scenarios": {
                "type": "array",
                "minItems": NUM_SCENARIOS,
                "maxItems": NUM_SCENARIOS,
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "What to accomplish in the browser, in plain language - a "
                                           "goal, not literal click-by-click steps. A separate agent will "
                                           "actually carry it out and decide the exact actions needed.",
                        },
                        "predicted_outcome": {
                            "type": "string",
                            "description": "What you predict the page will show once the goal is accomplished.",
                        },
                    },
                    "required": ["goal", "predicted_outcome"],
                },
            },
        },
        "required": ["reasoning", "scenarios"],
    },
}

CASTING_SYSTEM_PROMPT = """You are proposing test scenarios for exploratory testing of a small web app, given
a snapshot of its current page.

Propose exactly {n} distinct scenarios worth trying. Each scenario is a GOAL to accomplish in the browser
(e.g. "click the Yes button and check the response"), not a literal step-by-step script - a separate agent
will actually carry it out and decide the exact clicks/typing needed. For each, state what you predict the
page will show once the goal is accomplished.

Favor genuinely distinct scenarios over trivial variations of the same idea - think about what's actually
worth checking on a page like this, not just the two most obvious buttons.

Call submit_test_scenarios with your answer.""".format(n=NUM_SCENARIOS)


def validate_casting_response(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    if not isinstance(data.get("reasoning"), str):
        errors.append("'reasoning' must be a string")

    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != NUM_SCENARIOS:
        errors.append(f"'scenarios' must be a list of exactly {NUM_SCENARIOS} items")
    else:
        for i, s in enumerate(scenarios):
            if not isinstance(s, dict):
                errors.append(f"scenarios[{i}] must be an object")
                continue
            if not isinstance(s.get("goal"), str) or not s["goal"]:
                errors.append(f"scenarios[{i}].goal must be a non-empty string")
            if not isinstance(s.get("predicted_outcome"), str) or not s["predicted_outcome"]:
                errors.append(f"scenarios[{i}].predicted_outcome must be a non-empty string")
    return errors


SUBMIT_SCENARIO_RESULT_TOOL = {
    "name": "submit_scenario_result",
    "description": "Call this once you've carried out the scenario in the browser and observed the actual outcome.",
    "input_schema": {
        "type": "object",
        "properties": {
            "observed_outcome": {"type": "string", "description": "What actually happened, described plainly."},
            "matches_prediction": {"type": "boolean", "description": "Whether the observed outcome matches what was predicted."},
            "reasoning": {"type": "string", "description": "Why you believe the outcome does or doesn't match."},
        },
        "required": ["observed_outcome", "matches_prediction", "reasoning"],
    },
}


def validate_scenario_result(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    if not isinstance(data.get("observed_outcome"), str) or not data["observed_outcome"]:
        errors.append("'observed_outcome' must be a non-empty string")
    if not isinstance(data.get("matches_prediction"), bool):
        errors.append("'matches_prediction' must be a boolean")
    if not isinstance(data.get("reasoning"), str):
        errors.append("'reasoning' must be a string")
    return errors


def _cache_breakpoint(tools: list[dict], system: str) -> tuple[list[dict], list[dict]]:
    """Same trick as engine/client.py's _cache_breakpoint - the Playwright
    MCP tool list is large (~24 tools) and byte-identical across every
    turn of every scenario, so marking it (plus the system prompt) as a
    cache breakpoint meaningfully cuts cost with zero behavioral change."""
    cached_tools = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}] if tools else tools
    cached_system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return cached_tools, cached_system


def mcp_tool_to_anthropic(tool) -> dict:
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


async def run_scenario(anthropic_client: Anthropic, session: ClientSession, mcp_tools: list[dict], scenario: dict, scenario_number: int, model: str) -> dict:
    """Carries out one scenario via a real multi-turn agentic loop against
    Playwright MCP tools. tool_choice is deliberately NOT forced - the
    model freely chooses among browser actions each turn; the system
    prompt instructs it to call submit_scenario_result once it's
    confident about the outcome. Hard-capped at MAX_SCENARIO_TURNS as a
    code-level safety net - hitting the cap is reported honestly as
    turn_limit_exceeded, never silently treated as success."""
    tools = [*mcp_tools, SUBMIT_SCENARIO_RESULT_TOOL]
    system = f"""You are carrying out one exploratory test scenario against a live web app at {FRONTEND_URL},
using real browser-automation tools.

Goal: {scenario['goal']}
Predicted outcome: {scenario['predicted_outcome']}

Start by navigating to {FRONTEND_URL} (fresh - ignore any state left over from a previous scenario), then
use the available tools to accomplish the goal. Once you've observed the actual outcome, call
submit_scenario_result with what you found and whether it matches the prediction - do not call it before
you've actually observed a real result in the browser."""

    request_tools, request_system = _cache_breakpoint(tools, system)
    messages = [{"role": "user", "content": "Begin."}]

    for turn in range(1, MAX_SCENARIO_TURNS + 1):
        message = anthropic_client.messages.create(
            model=model, max_tokens=2048, system=request_system, tools=request_tools, messages=messages,
        )
        messages.append({"role": "assistant", "content": message.content})

        tool_uses = [b for b in message.content if b.type == "tool_use"]
        if not tool_uses:
            return {"status": "no_tool_call", "turns_used": turn}

        result_block = next((b for b in tool_uses if b.name == "submit_scenario_result"), None)
        if result_block is not None:
            errors = validate_scenario_result(result_block.input)
            if errors:
                print(f"    [scenario {scenario_number}] malformed submit_scenario_result: {errors} - treating as unresolved")
                return {"status": "malformed_result", "turns_used": turn, "errors": errors}
            print(f"    [scenario {scenario_number}] resolved after {turn} turn(s)")
            return {"status": "completed", "turns_used": turn, **result_block.input}

        tool_results = []
        for block in tool_uses:
            print(f"    [scenario {scenario_number}] turn {turn}: {block.name}({block.input})")
            mcp_result = await session.call_tool(block.name, block.input)
            text = "\n".join(c.text for c in mcp_result.content if hasattr(c, "text"))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": text or "(no textual output)",
                "is_error": bool(getattr(mcp_result, "isError", False)),
            })
        messages.append({"role": "user", "content": tool_results})

    return {"status": "turn_limit_exceeded", "turns_used": MAX_SCENARIO_TURNS}


async def main():
    # Load the repo-root .env, which carries the Bedrock config (ENGINE_USE_BEDROCK,
    # AWS_REGION, AWS_PROFILE). The PoC's own .env only ever held a direct API key, so
    # loading it alone would send this down the direct-API path build_client falls back to.
    load_dotenv(_REPO_ROOT / ".env")
    anthropic_client = build_client()
    model = default_model()
    print(f"Using model {model} ({'Bedrock' if 'claude-sonnet-5' in model else 'direct API'}).")

    base_dir = Path(__file__).parent
    out_dir = base_dir / "results"

    try:
        httpx.get(BACKEND_DOCS_URL, timeout=5.0)
    except httpx.TransportError:
        raise SystemExit("Backend isn't running. Start it first: uvicorn sut:app --port 8010")
    try:
        httpx.get(FRONTEND_URL, timeout=5.0)
    except httpx.TransportError:
        raise SystemExit("Frontend isn't running. Start it first: cd frontend && npm run dev")

    server_params = StdioServerParameters(command=NPX_CMD, args=["-y", "@playwright/mcp@latest"])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools_raw = (await session.list_tools()).tools
            mcp_tools = [mcp_tool_to_anthropic(t) for t in mcp_tools_raw]
            print(f"Connected to Playwright MCP - {len(mcp_tools)} tools available.")

            print(f"Navigating to {FRONTEND_URL} for the initial snapshot...")
            await session.call_tool("browser_navigate", {"url": FRONTEND_URL})
            snapshot_result = await session.call_tool("browser_snapshot", {})
            snapshot_text = "\n".join(c.text for c in snapshot_result.content if hasattr(c, "text"))
            print(snapshot_text)

            print(f"\nAsking Claude to propose {NUM_SCENARIOS} test scenarios...")
            casting = call_tool_with_retry(
                anthropic_client,
                model=model,
                system=CASTING_SYSTEM_PROMPT,
                tools=[CASTING_TOOL],
                tool_name="submit_test_scenarios",
                user_message=json.dumps({"page_snapshot": snapshot_text}, indent=2),
                max_tokens=1024,
                validate_fn=validate_casting_response,
            )
            print(f"  reasoning: {casting['reasoning']}")

            scenario_results = []
            for i, scenario in enumerate(casting["scenarios"], start=1):
                print(f"\nScenario {i}: {scenario['goal']}")
                print(f"  predicted: {scenario['predicted_outcome']}")
                result = await run_scenario(anthropic_client, session, mcp_tools, scenario, i, model)
                print(f"  status: {result['status']}")
                if result["status"] == "completed":
                    print(f"  observed: {result['observed_outcome']}")
                    print(f"  matches_prediction: {result['matches_prediction']}")
                scenario_results.append({"scenario": scenario, **result})

    output = {
        "num_scenarios": NUM_SCENARIOS,
        "casting_reasoning": casting["reasoning"],
        "scenario_results": scenario_results,
    }
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "output.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nWrote result to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
