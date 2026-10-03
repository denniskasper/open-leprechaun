"""Cron expressions for scheduled tasks (ticket 42).

The classic five fields — minute, hour, day of month, month, day of week —
each a `*`, a number, a range, a step or a comma-separated list of those.
Day of week counts from Sunday as 0, and 7 is Sunday too. Where both day
fields are restricted a day matching either fires, as cron has always read
them.

A schedule is read on the Admin's wall clock (Europe/Berlin, the clock every
other date in this application follows), so "0 6 * * *" stays six in the
morning across a clock change. A wall time the change skips does not fire
that day; one it repeats fires once.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from open_leprechaun.services.fx import BERLIN

# How far ahead a schedule is searched: far enough to reach the next leap day
# from anywhere, including across a century year that is not a leap year.
_HORIZON_DAYS = 366 * 8 + 2


class InvalidCronError(ValueError):
    """The expression names no schedule; the message says which part and why."""


@dataclass(frozen=True)
class _Schedule:
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    # A day field left as `*` restricts nothing — it never satisfies the
    # either-day rule on its own.
    days_restricted: bool
    weekdays_restricted: bool

    def fires_on(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        in_days = day.day in self.days
        # date.isoweekday() counts Monday 1 to Sunday 7; cron's Sunday is 0.
        in_weekdays = day.isoweekday() % 7 in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return in_days or in_weekdays
        return in_days and in_weekdays


_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)


def validate(expression: str) -> None:
    """Raise InvalidCronError unless the expression names a schedule that
    will fire."""
    next_fire(expression, datetime.now(UTC))


def next_fire(expression: str, after: datetime) -> datetime:
    """The first instant strictly after `after` at which the expression
    fires."""
    schedule = _parse(expression)
    local = after.astimezone(BERLIN)
    day = local.date()
    for _ in range(_HORIZON_DAYS):
        if schedule.fires_on(day):
            for hour in schedule.hours:
                for minute in schedule.minutes:
                    candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=BERLIN)
                    fires_at = candidate.astimezone(UTC)
                    if fires_at.astimezone(BERLIN).replace(tzinfo=None) != candidate.replace(
                        tzinfo=None
                    ):
                        # The clock change skips this wall time.
                        continue
                    if fires_at > after:
                        return fires_at
        day += timedelta(days=1)
    raise InvalidCronError(f"'{expression}' never fires — no such day exists.")


def _parse(expression: str) -> _Schedule:
    parts = expression.split()
    if len(parts) != len(_FIELDS):
        raise InvalidCronError(
            "A cron expression has five fields: minute, hour, day of month, month, day of week."
        )
    minutes, hours, days, months, weekdays = (
        _values(part, name, low, high)
        for part, (name, low, high) in zip(parts, _FIELDS, strict=True)
    )
    return _Schedule(
        minutes=tuple(sorted(minutes)),
        hours=tuple(sorted(hours)),
        days=frozenset(days),
        months=frozenset(months),
        # 7 is Sunday as well as 0.
        weekdays=frozenset(weekday % 7 for weekday in weekdays),
        days_restricted=not parts[2].startswith("*"),
        weekdays_restricted=not parts[4].startswith("*"),
    )


def _values(field: str, name: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for item in field.split(","):
        span, slash, step_text = item.partition("/")
        step = _number(step_text, name) if slash else 1
        if step < 1:
            raise InvalidCronError(f"The {name} field steps by {step}; a step is at least 1.")
        if span == "*":
            first, last = low, high
        else:
            first_text, dash, last_text = span.partition("-")
            first = _number(first_text, name)
            # "5/15" reads as "from 5, every 15" — the span runs to the end.
            last = _number(last_text, name) if dash else (high if slash else first)
        if not low <= first <= high or not low <= last <= high:
            raise InvalidCronError(
                f"The {name} field runs from {low} to {high}; '{item}' does not."
            )
        if first > last:
            raise InvalidCronError(f"The {name} range '{span}' ends before it starts.")
        values.update(range(first, last + 1, step))
    return values


def _number(text: str, name: str) -> int:
    if not text.isascii() or not text.isdigit():
        raise InvalidCronError(f"The {name} field takes numbers; '{text}' is not one.")
    return int(text)
