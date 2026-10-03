"""Cron expressions (ticket 42): the five-field schedule an Admin types for a
scheduled task, read on the Admin's wall clock.

The seam is the pure schedule — an expression in, the next instant it fires
out. Expected instants are worked by hand from a calendar, never recomputed.
"""

from datetime import UTC, datetime

import pytest

from open_leprechaun.services.cron import InvalidCronError, next_fire


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def test_every_quarter_hour_fires_on_the_next_quarter():
    assert next_fire("*/15 * * * *", utc(2026, 10, 3, 9, 7)) == utc(2026, 10, 3, 9, 15)


def test_the_next_fire_is_strictly_after_the_instant_asked_from():
    assert next_fire("*/15 * * * *", utc(2026, 10, 3, 9, 15)) == utc(2026, 10, 3, 9, 30)


def test_a_daily_time_is_read_on_the_berlin_wall_clock():
    # 06:00 in Berlin is 04:00 UTC in summer and 05:00 UTC in winter.
    assert next_fire("0 6 * * *", utc(2026, 7, 1, 12, 0)) == utc(2026, 7, 2, 4, 0)
    assert next_fire("0 6 * * *", utc(2026, 12, 1, 12, 0)) == utc(2026, 12, 2, 5, 0)


def test_lists_and_ranges_name_several_values():
    # 3 October 2026 is a Saturday; the next weekday is Monday the 5th.
    assert next_fire("30 8,20 * * 1-5", utc(2026, 10, 3, 0, 0)) == utc(2026, 10, 5, 6, 30)
    assert next_fire("30 8,20 * * 1-5", utc(2026, 10, 5, 7, 0)) == utc(2026, 10, 5, 18, 30)


def test_sunday_answers_to_both_zero_and_seven():
    # The first Sunday after Saturday 3 October 2026 is the 4th.
    assert next_fire("0 12 * * 0", utc(2026, 10, 3, 0, 0)) == utc(2026, 10, 4, 10, 0)
    assert next_fire("0 12 * * 7", utc(2026, 10, 3, 0, 0)) == utc(2026, 10, 4, 10, 0)


def test_day_of_month_and_day_of_week_together_mean_either():
    # The 15th or any Monday — Monday 5 October comes first.
    assert next_fire("0 0 15 * 1", utc(2026, 10, 3, 0, 0)) == utc(2026, 10, 4, 22, 0)


def test_a_month_and_day_wait_for_the_year_to_come_round():
    assert next_fire("0 0 1 1 *", utc(2026, 10, 3, 0, 0)) == utc(2026, 12, 31, 23, 0)


def test_a_leap_day_schedule_waits_for_the_leap_year():
    assert next_fire("0 12 29 2 *", utc(2026, 10, 3, 0, 0)) == utc(2028, 2, 29, 11, 0)


def test_a_wall_time_the_clock_skips_does_not_fire_that_day():
    # Clocks jump 02:00 -> 03:00 on 28 March 2027; 02:30 does not exist then.
    assert next_fire("30 2 * * *", utc(2027, 3, 27, 12, 0)) == utc(2027, 3, 29, 0, 30)


def test_a_wall_time_the_clock_repeats_fires_once():
    # Clocks fall 03:00 -> 02:00 on 25 October 2026; 02:30 happens twice.
    first = next_fire("30 2 * * *", utc(2026, 10, 24, 12, 0))
    assert first == utc(2026, 10, 25, 0, 30)
    assert next_fire("30 2 * * *", first) == utc(2026, 10, 26, 1, 30)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "1,,2 * * * *",
        "0 0 31 2 *",
    ],
)
def test_an_expression_that_names_no_schedule_is_refused(expression):
    with pytest.raises(InvalidCronError):
        next_fire(expression, utc(2026, 10, 3, 0, 0))


def test_a_refusal_says_which_field_is_wrong():
    with pytest.raises(InvalidCronError, match="hour"):
        next_fire("0 24 * * *", utc(2026, 10, 3, 0, 0))
