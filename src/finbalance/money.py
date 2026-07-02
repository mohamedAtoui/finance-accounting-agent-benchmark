"""Money primitive: signed integer cents.

The single most important correctness decision in the whole benchmark is that
money is represented as ``int`` cents everywhere in the ledger path — never
``float``. ``decimal.Decimal`` is used *only* at the parse boundary (when an
agent submits a balance sheet as a decimal string) and immediately converted to
integer cents. The FinBalance "$0.01 tolerance" therefore becomes exactly
``tol_cents=1`` and lives in one place: :func:`within_tolerance`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# A signed integer number of cents. Positive/negative both valid.
Cents = int

_CENT = Decimal("0.01")


def parse_amount(raw: "str | int | float | Decimal") -> Cents:
    """Parse an external amount into integer cents, rounding half-up at $0.01.

    Accepts strings ("123.45", "-0.10"), ints (already dollars? no — see below),
    floats, or Decimals. To avoid ambiguity we treat *ints* as whole dollars only
    when they arrive as ``int``; callers inside the ledger always pass cents
    directly and never route through this function.
    """
    if isinstance(raw, bool):  # bool is an int subclass; reject to avoid surprises
        raise TypeError("bool is not a valid amount")
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"cannot parse amount: {raw!r}") from exc
    cents = (d.quantize(_CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value()
    return int(cents)


def fmt(cents: Cents) -> str:
    """Format signed integer cents as a plain decimal string, e.g. -12345 -> '-123.45'."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"


def within_tolerance(a: Cents, b: Cents, tol_cents: Cents = 1) -> bool:
    """True if two cent amounts match within ``tol_cents`` (default $0.01)."""
    return abs(a - b) <= tol_cents
