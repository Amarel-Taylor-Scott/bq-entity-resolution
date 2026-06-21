"""Dependency-free cron evaluation for leaf scheduling.

Leaf-based resolution lets a leaf declare ``schedule="cron"`` (typically the
``old×old`` merge-repair leaf) so it never changes the default per-run cost and
only runs on its own cadence. The project has no cron dependency, so this module
implements just enough of the standard 5-field cron spec to answer two
questions the executor needs:

- ``cron_matches(expr, dt)`` — does this datetime match the cron expression?
- ``is_cron_due(expr, now, last_run)`` — has a firing occurred since ``last_run``
  that we have not serviced yet (i.e. is the leaf due to run now)?

Supported field syntax: ``*``, ``*/n`` (step), ``a`` (single), ``a-b`` (range),
``a-b/n`` (stepped range), and comma-separated lists of the above. Fields are
minute (0-59), hour (0-23), day-of-month (1-31), month (1-12), day-of-week (0-6,
0=Sunday; 7 also accepted as Sunday). Vixie-cron day semantics: when *both*
day-of-month and day-of-week are restricted (neither is ``*``), a datetime
matches when *either* field matches.
"""

from __future__ import annotations

from datetime import datetime, timedelta

__all__ = ["cron_matches", "is_cron_due", "CronError"]

# Bound the look-back when searching for a pending firing so a misconfigured
# expression that never matches can't spin forever (well past any real cadence).
_MAX_LOOKBACK_MINUTES = 366 * 24 * 60

_FIELD_BOUNDS = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),   # day of week (0=Sun)
)


class CronError(ValueError):
    """Raised when a cron expression cannot be parsed."""


def _parse_field(field: str, lo: int, hi: int, *, dow: bool = False) -> set[int]:
    """Expand one cron field into the concrete set of values it matches."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"empty cron field component in {field!r}")
        step = 1
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronError(f"bad step {step_s!r} in {field!r}") from exc
            if step <= 0:
                raise CronError(f"non-positive step in {field!r}")
        else:
            base = part

        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a_s, _, b_s = base.partition("-")
            try:
                start, end = int(a_s), int(b_s)
            except ValueError as exc:
                raise CronError(f"bad range {base!r} in {field!r}") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronError(f"bad value {base!r} in {field!r}") from exc

        # Normalise Sunday-as-7 to 0 for the day-of-week field.
        if dow:
            if start == 7:
                start = 0
            if end == 7:
                end = 0
            if start > end:  # e.g. a literal "7" normalised below a 0 end
                start, end = end, start

        if start < lo or end > hi or start > end:
            raise CronError(
                f"value out of bounds [{lo},{hi}] in {field!r}: {base!r}"
            )
        values.update(range(start, end + 1, step))
    return values


def cron_matches(expr: str, dt: datetime) -> bool:
    """True when ``dt`` (minute granularity) satisfies the cron ``expr``."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"cron expression must have 5 fields, got {len(fields)}: {expr!r}"
        )
    minute_s, hour_s, dom_s, month_s, dow_s = fields
    (mn_lo, mn_hi), (hr_lo, hr_hi), (dom_lo, dom_hi), (mo_lo, mo_hi), (dw_lo, dw_hi) = (
        _FIELD_BOUNDS
    )
    minutes = _parse_field(minute_s, mn_lo, mn_hi)
    hours = _parse_field(hour_s, hr_lo, hr_hi)
    doms = _parse_field(dom_s, dom_lo, dom_hi)
    months = _parse_field(month_s, mo_lo, mo_hi)
    dows = _parse_field(dow_s, dw_lo, dw_hi, dow=True)

    if dt.minute not in minutes or dt.hour not in hours or dt.month not in months:
        return False

    # Python weekday(): Mon=0..Sun=6 → convert to cron Sun=0..Sat=6.
    cron_dow = (dt.weekday() + 1) % 7
    dom_restricted = dom_s.strip() != "*"
    dow_restricted = dow_s.strip() != "*"
    dom_hit = dt.day in doms
    dow_hit = cron_dow in dows

    if dom_restricted and dow_restricted:
        return dom_hit or dow_hit  # Vixie semantics
    return dom_hit and dow_hit


def is_cron_due(
    expr: str | None,
    *,
    now: datetime | None,
    last_run: datetime | None = None,
) -> bool:
    """True when a cron firing has occurred in ``(last_run, now]``.

    Returns ``False`` when there is nothing to evaluate against (``expr`` or
    ``now`` is ``None``). When ``last_run`` is ``None`` the leaf has never run,
    so any firing within the bounded look-back counts as due (first-run).
    """
    if not expr or now is None:
        return False
    now = now.replace(second=0, microsecond=0)
    if last_run is not None:
        lower = last_run.replace(second=0, microsecond=0)
    else:
        lower = now - timedelta(minutes=_MAX_LOOKBACK_MINUTES)

    t = now
    steps = 0
    while t > lower and steps <= _MAX_LOOKBACK_MINUTES:
        if cron_matches(expr, t):
            return True
        t -= timedelta(minutes=1)
        steps += 1
    return False
