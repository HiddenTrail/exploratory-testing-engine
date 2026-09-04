"""The SUTAdapter interface: everything genuinely per-SUT that the generic
checkpoint loop and report renderer need supplied. A frozen dataclass rather
than a Protocol/ABC - matches the existing procedural style (free functions +
module constants) that each experiment already used, with no self/inheritance
boilerplate to invent. One instance is built at import time and only ever
read during a run.

engine/ code must never import from engine/adapters/ - adapters import from
engine, never the reverse. This module has no knowledge of any concrete
adapter.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

_DEFAULT_CASTING_MAX_TOKENS: Callable[[int], int] = lambda budget: 4096 if budget <= 8 else 6144


@dataclass(frozen=True)
class SUTAdapter:
    name: str
    display_name: str

    # How to reach the SUT over HTTP. Empty for a SUT that isn't a web service -
    # see check_sut_ready / fetch_happy_day_example below, and validate_adapter
    # for the rule that stops an adapter supplying neither.
    base_url: str = ""
    test_endpoint_path: str = ""
    docs_path: str = "/docs"
    sut_ready_timeout: float = 5.0

    # Onboarding evidence shown verbatim to the Driver and rendered in the report.
    api_schema_doc: str = ""
    onboarding_extra: dict[str, Any] = field(default_factory=dict)
    happy_day_request: dict[str, Any] = field(default_factory=dict)

    # Casting (test-proposal) contract - the genuinely per-SUT part.
    casting_tool_schema: dict | None = None
    casting_system_prompt: Callable[[int, bool], str] | None = None
    validate_casting_response: Callable[[Any], list[str]] | None = None
    casting_max_tokens: Callable[[int], int] = _DEFAULT_CASTING_MAX_TOKENS

    # Execution.
    execute_test: Callable[[dict, int], dict] | None = None

    # Reaching the SUT at all. Both default to the HTTP behaviour every adapter
    # up to now has wanted, and both exist so that a SUT which is not a web
    # service can be one: the checkpoint loop itself only ever calls
    # execute_test, so these two were the whole of the engine's HTTP assumption.
    #
    # check_sut_ready is asked once, before anything is spent, and should raise
    # SystemExit with an actionable message rather than return a flag - a run
    # against a SUT that isn't there costs API calls to discover otherwise.
    #
    # fetch_happy_day_example must return {"request": ..., "response": ...};
    # the two halves go into the Driver's onboarding evidence verbatim and are
    # rendered by the adapter's own render_onboarding_section, so their shape is
    # the adapter's business and nothing generic reads inside them.
    check_sut_ready: Callable[["SUTAdapter"], None] | None = None
    fetch_happy_day_example: Callable[["SUTAdapter"], dict] | None = None

    # Optional hooks; None falls back to an engine-generic default.
    redact_history_for_model: Callable[[list[dict]], list[dict]] | None = None
    describe_test_for_log: Callable[[dict], str] | None = None
    describe_result_for_log: Callable[[dict], str] | None = None

    # Report rendering hooks - the adapter owns request/response-shape rendering.
    render_test_entry: Callable[[dict], str] | None = None
    render_onboarding_section: Callable[[str, dict, dict], str] | None = None
    report_title: str | None = None

    # Suggested run-level defaults; RunConfig/CLI flags may override.
    default_max_checkpoints: int = 4
    default_first_round_test_budget: int = 12
    default_test_budget: int = 8


_REQUIRED_FIELDS = (
    "name", "display_name",
    "casting_tool_schema", "casting_system_prompt", "validate_casting_response",
    "execute_test", "render_test_entry", "render_onboarding_section",
)

# Reaching the SUT is required, but there are two ways to supply it and an
# adapter must pick one wholly. base_url/test_endpoint_path are no longer in
# _REQUIRED_FIELDS because a SUT need not be a web service; this pair of rules
# is what keeps that from silently degrading into an adapter that supplies
# neither and fails at the first call instead of at validation.
_HTTP_FIELDS = ("base_url", "test_endpoint_path")
_REACH_HOOKS = ("check_sut_ready", "fetch_happy_day_example")


def validate_adapter(adapter: SUTAdapter) -> None:
    missing = [f for f in _REQUIRED_FIELDS if getattr(adapter, f) in (None, "")]
    if missing:
        raise ValueError(f"Adapter '{adapter.name}' is missing required field(s): {', '.join(missing)}")

    # Partial hooks are the dangerous case, not absent ones: an adapter that
    # overrides only the readiness probe still gets the HTTP happy-day fetch,
    # which for a non-HTTP SUT means a confusing connection error at the one
    # moment the run looked like it had started successfully.
    hooks_given = [f for f in _REACH_HOOKS if getattr(adapter, f) is not None]
    if hooks_given and len(hooks_given) != len(_REACH_HOOKS):
        absent = ", ".join(f for f in _REACH_HOOKS if f not in hooks_given)
        raise ValueError(
            f"Adapter '{adapter.name}' overrides {', '.join(hooks_given)} but not {absent}. "
            f"Supply both or neither: a half-overridden SUT still falls back to HTTP for the rest."
        )
    if not hooks_given:
        no_http = [f for f in _HTTP_FIELDS if getattr(adapter, f) in (None, "")]
        if no_http:
            raise ValueError(
                f"Adapter '{adapter.name}' has no {', '.join(no_http)} and does not override "
                f"{' / '.join(_REACH_HOOKS)}, so there is no way to reach its SUT. Set the HTTP "
                f"fields for a web service, or supply both hooks for anything else."
            )
