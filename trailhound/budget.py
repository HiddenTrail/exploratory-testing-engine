"""A hard spending limit for one run: it stops the run, whatever else goes wrong.

Checkpoints, test budgets and the retry limit already bound a run, but each is a
separate number someone can set high by mistake, and a bug in the loop could call the
model again and again. This is the last line: before every model call, the engine
checks what the run has spent so far, and raises BudgetExceeded once it has made
TRAILHOUND_MAX_MODEL_CALLS calls or spent about TRAILHOUND_MAX_COST_USD. The runner
stops the run there and still writes everything it has (issue #255, for the CI
pipeline, and on every machine).

The cost is an estimate at list prices for a Sonnet-class model, from the token counts
each response reports. The check runs before a call, so the last call can go over the
limit by its own cost, about $0.15 at most.
"""

from __future__ import annotations

from trailhound import settings

# Per million tokens: input, output, cache write, cache read.
PRICE_PER_MTOK = (3.00, 15.00, 3.75, 0.30)
_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Defaults well above a normal run (about $0.60 and 10 to 20 calls), far below a runaway.
DEFAULT_MAX_COST_USD = 3.00
DEFAULT_MAX_MODEL_CALLS = 80
_COST = "MAX_COST_USD"
_CALLS = "MAX_MODEL_CALLS"


class BudgetExceeded(RuntimeError):
    """The run hit its spending limit."""


def estimated_cost(tokens: dict) -> float:
    """Dollars for a dict of token counts, at PRICE_PER_MTOK."""
    return sum(tokens.get(k, 0) * p for k, p in zip(_TOKEN_KEYS, PRICE_PER_MTOK)) / 1_000_000


def _limit(name: str, default: float, cast) -> tuple[float, str]:
    """The limit and the variable it came from, so a stop names the one that was set."""
    raw, var = settings.read(name)
    if not raw:
        return default, var
    try:
        value = cast(raw)
    except ValueError:
        raise SystemExit(f"{var}={raw!r} isn't a number.")
    if value <= 0:
        raise SystemExit(f"{var} must be above 0; the limit can be raised, not switched off.")
    return value, var


class SpendGuard:
    def __init__(self, max_cost_usd: float = DEFAULT_MAX_COST_USD, max_calls: int = DEFAULT_MAX_MODEL_CALLS,
                 cost_var: str = settings.PREFIX + _COST, calls_var: str = settings.PREFIX + _CALLS):
        self.max_cost_usd, self.max_calls = max_cost_usd, max_calls
        self.cost_var, self.calls_var = cost_var, calls_var
        self.calls = 0
        self.tokens = dict.fromkeys(_TOKEN_KEYS, 0)

    @classmethod
    def from_env(cls) -> "SpendGuard":
        max_cost, cost_var = _limit(_COST, DEFAULT_MAX_COST_USD, float)
        max_calls, calls_var = _limit(_CALLS, DEFAULT_MAX_MODEL_CALLS, int)
        return cls(max_cost, int(max_calls), cost_var, calls_var)

    @property
    def cost(self) -> float:
        return estimated_cost(self.tokens)

    def check(self) -> None:
        """Raise BudgetExceeded if another model call would be past the limit."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"Stopped by the spending limit: {self.calls} model calls made, the limit is "
                                 f"{self.max_calls} ({self.calls_var}).")
        if self.cost >= self.max_cost_usd:
            raise BudgetExceeded(f"Stopped by the spending limit: about ${self.cost:.2f} spent, the limit is "
                                 f"${self.max_cost_usd:.2f} ({self.cost_var}).")

    def record(self, usage) -> None:
        """Count one model response and its tokens."""
        self.calls += 1
        if usage is None:
            return
        for key in _TOKEN_KEYS:
            self.tokens[key] += getattr(usage, key, 0) or 0


_GUARD = SpendGuard()


def start_run() -> SpendGuard:
    """A fresh guard for a new run, with the limits from the environment."""
    global _GUARD
    _GUARD = SpendGuard.from_env()
    return _GUARD


def guard() -> SpendGuard:
    return _GUARD
