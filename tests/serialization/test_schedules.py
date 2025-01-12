import json
from datetime import datetime, timedelta

import marshmallow
import pendulum
import pytest

import prefect
from prefect import __version__
from prefect.schedules import schedules, clocks, filters, adjustments

from prefect.serialization.schedule import ScheduleSchema


def serialize_and_deserialize(schedule: schedules.Schedule):
    schema = ScheduleSchema()
    return schema.load(json.loads(json.dumps(schema.dump(schedule))))


def test_serialize_complex_schedule():
    dt = pendulum.datetime(2019, 1, 3)
    s = schedules.Schedule(
        # fire every hour
        clocks=[clocks.IntervalClock(timedelta(hours=1))],
        # only on weekdays
        filters=[filters.is_weekday],
        # only at 9am or 3pm
        or_filters=[
            filters.between_times(pendulum.time(9), pendulum.time(9)),
            filters.between_times(pendulum.time(15), pendulum.time(15)),
        ],
        # not on january 8
        not_filters=[filters.between_dates(1, 8, 1, 8)],
        # add three hours
        adjustments=[adjustments.add(timedelta(hours=3))],
    )

    s2 = serialize_and_deserialize(s)

    assert s2.next(8, after=dt) == [
        dt.replace(hour=12),
        dt.replace(hour=18),
        dt.add(days=1).replace(hour=12),
        dt.add(days=1).replace(hour=18),
        # skip weekend
        dt.add(days=4).replace(hour=12),
        dt.add(days=4).replace(hour=18),
        # skip jan 8!
        dt.add(days=6).replace(hour=12),
        dt.add(days=6).replace(hour=18),
    ]


def test_serialize_multiple_clocks():

    dt = pendulum.datetime(2019, 1, 1)
    s = schedules.Schedule(
        clocks=[
            clocks.IntervalClock(timedelta(days=1)),
            clocks.IntervalClock(
                timedelta(hours=12), start_date=pendulum.datetime(2019, 1, 3)
            ),
        ]
    )
    s2 = serialize_and_deserialize(s)

    assert s2.next(6, after=dt) == [
        dt.add(days=1),
        dt.add(days=2),
        dt.add(days=2, hours=12),
        dt.add(days=3),
        dt.add(days=3, hours=12),
        dt.add(days=4),
    ]


class TestBackwardsCompatibility:
    """
    Tests that old-style (pre-0.6.1) schedules are properly deserialized as new-style schedules
    """

    def test_interval_schedule(self):
        serialized = {
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "end_date": None,
            "interval": 3720000000,
            "__version__": "0.6.0+87.g44ac9ba5",
            "type": "IntervalSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 1, 1)) == [
            pendulum.datetime(2019, 1, 2, 3, 0, 0),
            pendulum.datetime(2019, 1, 2, 4, 2, 0),
            pendulum.datetime(2019, 1, 2, 5, 4, 0),
            pendulum.datetime(2019, 1, 2, 6, 6, 0),
            pendulum.datetime(2019, 1, 2, 7, 8, 0),
            pendulum.datetime(2019, 1, 2, 8, 10, 0),
            pendulum.datetime(2019, 1, 2, 9, 12, 0),
            pendulum.datetime(2019, 1, 2, 10, 14, 0),
            pendulum.datetime(2019, 1, 2, 11, 16, 0),
            pendulum.datetime(2019, 1, 2, 12, 18, 0),
        ]

    def test_interval_schedule_with_end_date(self):
        serialized = {
            "interval": 3720000000,
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "end_date": {"dt": "2020-01-01T00:00:00", "tz": "UTC"},
            "__version__": "0.6.0+87.g44ac9ba5",
            "type": "IntervalSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 12, 31, 20)) == [
            pendulum.datetime(2019, 12, 31, 20, 36, 0),
            pendulum.datetime(2019, 12, 31, 21, 38, 0),
            pendulum.datetime(2019, 12, 31, 22, 40, 0),
            pendulum.datetime(2019, 12, 31, 23, 42, 0),
        ]

    def test_cron_schedule(self):
        serialized = {
            "cron": "3 0 * * *",
            "start_date": None,
            "end_date": None,
            "__version__": "0.6.0+87.g44ac9ba5",
            "type": "CronSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 1, 1)) == [
            pendulum.datetime(2019, 1, 1, 0, 3, 0),
            pendulum.datetime(2019, 1, 2, 0, 3, 0),
            pendulum.datetime(2019, 1, 3, 0, 3, 0),
            pendulum.datetime(2019, 1, 4, 0, 3, 0),
            pendulum.datetime(2019, 1, 5, 0, 3, 0),
            pendulum.datetime(2019, 1, 6, 0, 3, 0),
            pendulum.datetime(2019, 1, 7, 0, 3, 0),
            pendulum.datetime(2019, 1, 8, 0, 3, 0),
            pendulum.datetime(2019, 1, 9, 0, 3, 0),
            pendulum.datetime(2019, 1, 10, 0, 3, 0),
        ]

    def test_cron_schedule_with_end_date(self):
        serialized = {
            "end_date": {"dt": "2020-01-01T00:00:00", "tz": "UTC"},
            "cron": "3 0 * * *",
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "__version__": "0.6.0+105.gce4aef06",
            "type": "CronSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 12, 31, 20)) == []

    def test_one_time_schedule(self):
        serialized = {
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "__version__": "0.6.0+105.gce4aef06",
            "type": "OneTimeSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 1, 1)) == [
            pendulum.datetime(2019, 1, 2, 3, 0, 0)
        ]

    def test_one_time_schedule_with_after(self):
        serialized = {
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "__version__": "0.6.0+105.gce4aef06",
            "type": "OneTimeSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2020, 1, 1)) == []

    def test_union_schedule(self):
        serialized = {
            "end_date": {"dt": "2020-01-01T00:00:00", "tz": "UTC"},
            "schedules": [
                {
                    "end_date": {"dt": "2020-01-01T00:00:00", "tz": "UTC"},
                    "interval": 3720000000,
                    "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
                    "__version__": "0.6.0+105.gce4aef06",
                    "type": "IntervalSchedule",
                },
                {
                    "end_date": {"dt": "2020-01-01T00:00:00", "tz": "UTC"},
                    "cron": "3 0 * * *",
                    "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
                    "__version__": "0.6.0+105.gce4aef06",
                    "type": "CronSchedule",
                },
            ],
            "start_date": {"dt": "2019-01-02T03:00:00", "tz": "UTC"},
            "__version__": "0.6.0+105.gce4aef06",
            "type": "UnionSchedule",
        }
        schema = ScheduleSchema()
        schedule = schema.load(serialized)
        assert schedule.next(10, after=pendulum.datetime(2019, 1, 1)) == [
            pendulum.datetime(2019, 1, 2, 3, 0, 0),
            pendulum.datetime(2019, 1, 2, 4, 2, 0),
            pendulum.datetime(2019, 1, 2, 5, 4, 0),
            pendulum.datetime(2019, 1, 2, 6, 6, 0),
            pendulum.datetime(2019, 1, 2, 7, 8, 0),
            pendulum.datetime(2019, 1, 2, 8, 10, 0),
            pendulum.datetime(2019, 1, 2, 9, 12, 0),
            pendulum.datetime(2019, 1, 2, 10, 14, 0),
            pendulum.datetime(2019, 1, 2, 11, 16, 0),
            pendulum.datetime(2019, 1, 2, 12, 18, 0),
        ]
