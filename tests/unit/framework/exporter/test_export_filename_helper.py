# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.framework.exporter.export_filename_helper

Pins the exported-file timestamp both export paths share: it follows EXPORT_FILENAME_TIMESTAMP_FMT and
is taken in UTC, not in the server's local timezone.
"""
from datetime import datetime, timedelta, timezone

from cmdb.framework.exporter.exporter_constants import EXPORT_FILENAME_TIMESTAMP_FMT
from cmdb.framework.exporter.export_filename_helper import build_export_filename_timestamp
# -------------------------------------------------------------------------------------------------------------------- #

# Slack allowed between the stamp and the assertion clock, so the test cannot fail on a slow machine
MAX_CLOCK_SKEW: timedelta = timedelta(minutes=5)


def test_timestamp_matches_the_export_filename_format() -> None:
    """The stamp is parseable with the shared strftime format (so it is filename-safe and stable)."""
    stamp = build_export_filename_timestamp()

    assert datetime.strptime(stamp, EXPORT_FILENAME_TIMESTAMP_FMT)


def test_timestamp_is_taken_in_utc() -> None:
    """The stamp tracks UTC rather than the server's local timezone."""
    stamp = build_export_filename_timestamp()

    parsed = datetime.strptime(stamp, EXPORT_FILENAME_TIMESTAMP_FMT).replace(tzinfo=timezone.utc)

    assert abs(parsed - datetime.now(timezone.utc)) < MAX_CLOCK_SKEW
