# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.manager.open_celium_managers.oc_license_manager

**OpenCelium's licence, not DataGerry's own** - every read here is a proxy onto another product's
`/subs` endpoints. The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector
is patched out at the OcBaseManager module path. Each read test stubs oc_get with a fake response and
asserts the endpoint, the parsed 2xx body, and OcLicenseGetError on a non-2xx response. No HTTP, no
Mongo.

**The month-boundary tests pin the timezone, not the implementation.** They used to compute the
expected value with the same expression the code uses (`datetime(2026, 3, 1).timestamp() * 1000`),
which cannot fail whatever the code does with the clock. They now run under a FIXED `TZ` and assert
absolute millisecond constants, so the two properties recorded as discussion-backlog #225 - the
window is the HOST's local month, and it ends a whole second before the month does - are visible and
will fail loudly the day that decision is taken.
"""
import json
import os
import time
from datetime import datetime, timezone
from http import HTTPStatus
from json import JSONDecodeError
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_license_manager import (
    OcLicenseManager,
    get_current_month_boundaries,
    LICENSE_ACTIVATION_URL,
    ACTIVE_LICENSE_URL,
    LICENSE_USAGE_URL,
)

from cmdb.open_celium.oc_constants import OC_DEFAULT_USAGE_PAGE, OC_DEFAULT_USAGE_SIZE

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'
MODULE_PATH: str = 'cmdb.manager.open_celium_managers.oc_license_manager'

MONTH_START: int = 1_700_000_000_000
MONTH_END: int = 1_700_999_999_000

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value

# The timezone the boundary tests run in, and the millisecond bounds the current implementation
# answers in it. Central European Time is deliberate: its DST switch falls INSIDE March, so the two
# ends of the window are an hour apart in offset
BOUNDARY_TIMEZONE: str = 'Europe/Berlin'

MARCH_2026_START_MS: int = 1_772_319_600_000
MARCH_2026_END_MS: int = 1_774_994_399_000
APRIL_2026_START_MS: int = 1_774_994_400_000

DECEMBER_2026_START_MS: int = 1_796_079_600_000
DECEMBER_2026_END_MS: int = 1_798_757_999_000

# What the window falls short of the true end of the month by, in milliseconds - a whole second
MISSING_MONTH_TAIL_MS: int = 1000


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


def _usage_url(page: int, size: int, start: int, end: int) -> str:
    """The usage URL as the manager builds it: page, size, then the window - urlencoded, in order."""
    return f"{LICENSE_USAGE_URL}?page={page}&size={size}&startDate={start}&endDate={end}"


@pytest.fixture(name='license_manager')
def fixture_license_manager() -> OcLicenseManager:
    """An OcLicenseManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcLicenseManager(MagicMock(), 'db_test')


@pytest.fixture(name='berlin_timezone')
def fixture_berlin_timezone() -> Iterator[None]:
    """
    Runs the test in a fixed local timezone, restoring the process' own afterwards

    `get_current_month_boundaries` reads the clock through naive `datetime`, so its answer depends on
    the PROCESS timezone - which is exactly what these tests need to hold still. tzset() is
    process-wide, hence the save/restore.
    """
    previous: str | None = os.environ.get('TZ')
    os.environ['TZ'] = BOUNDARY_TIMEZONE
    time.tzset()

    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = previous

        time.tzset()


def _frozen_datetime(frozen: datetime) -> type:
    """A `datetime` subclass whose `now()` is fixed; every other behaviour stays real."""
    class _FrozenDatetime(datetime):
        """`datetime` with a stopped clock."""

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            """The frozen moment, ignoring tz - the code under test passes none."""
            del tz

            return frozen

    return _FrozenDatetime


# ------------------------------------------------- get_license_activation ------------------------------------------- #

class TestGetLicenseActivation:
    """``get_license_activation`` GETs the activation-request endpoint."""

    def test_gets_and_returns_body(self, license_manager: OcLicenseManager) -> None:
        """A 2xx body is parsed and returned from the activation endpoint."""
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'activation': 'blob'})

        result = license_manager.get_license_activation()

        assert result == {'activation': 'blob'}
        license_manager.oc_connector.oc_get.assert_called_once_with(LICENSE_ACTIVATION_URL)

    def test_a_non_json_body_is_not_handled_at_all(self, license_manager: OcLicenseManager) -> None:
        """
        The activation request is read as JSON, whatever the route once documented

        The route promised "a text file"; `parse_response` cannot produce one - a 200 carrying plain
        text raises `JSONDecodeError`, which is not even the manager's own error type, so the route
        answers a generic 500 rather than its own message. Which of the two OpenCelium actually
        returns is discussion-backlog #224, and this is the assertion that will change when it is
        decided.
        """
        license_manager.oc_connector.oc_get.return_value = SimpleNamespace(
            status_code=OK_STATUS,
            text='-----BEGIN ACTIVATION REQUEST-----',
        )

        with pytest.raises(JSONDecodeError):
            license_manager.get_license_activation()

    def test_non_2xx_raises_get_error(self, license_manager: OcLicenseManager) -> None:
        """A non-2xx response raises OcLicenseGetError."""
        license_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcLicenseGetError):
            license_manager.get_license_activation()


# --------------------------------------------------- get_active_license --------------------------------------------- #

class TestGetActiveLicense:
    """``get_active_license`` GETs the active-license endpoint."""

    def test_gets_and_returns_body(self, license_manager: OcLicenseManager) -> None:
        """A 2xx body is parsed and returned from the active-license endpoint."""
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'type': 'BUSINESS'})

        result = license_manager.get_active_license()

        assert result == {'type': 'BUSINESS'}
        license_manager.oc_connector.oc_get.assert_called_once_with(ACTIVE_LICENSE_URL)

    def test_non_2xx_raises_get_error(self, license_manager: OcLicenseManager) -> None:
        """A non-2xx response raises OcLicenseGetError."""
        license_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcLicenseGetError):
            license_manager.get_active_license()


# --------------------------------------------------- get_license_usage ---------------------------------------------- #

class TestGetLicenseUsage:
    """``get_license_usage`` GETs the usage endpoint with paging + the current-month bounds."""

    def test_gets_with_paging_and_month_bounds(self, license_manager: OcLicenseManager) -> None:
        """Page/size and the month boundaries are appended to the usage endpoint."""
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'items': []})

        with patch(f'{MODULE_PATH}.get_current_month_boundaries', return_value=(MONTH_START, MONTH_END)):
            result = license_manager.get_license_usage(2, 10)

        assert result == {'items': []}
        license_manager.oc_connector.oc_get.assert_called_once_with(
            _usage_url(2, 10, MONTH_START, MONTH_END)
        )

    def test_it_defaults_to_the_paging_the_frontend_asks_for(self, license_manager: OcLicenseManager) -> None:
        """
        Called without paging, the shared defaults apply

        The route and the manager both default to the same page and size because both read them from
        `oc_constants` - they used to be two independent pairs of literals.
        """
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'items': []})

        with patch(f'{MODULE_PATH}.get_current_month_boundaries', return_value=(MONTH_START, MONTH_END)):
            license_manager.get_license_usage()

        license_manager.oc_connector.oc_get.assert_called_once_with(
            _usage_url(OC_DEFAULT_USAGE_PAGE, OC_DEFAULT_USAGE_SIZE, MONTH_START, MONTH_END)
        )

    def test_the_query_is_url_encoded(self, license_manager: OcLicenseManager) -> None:
        """
        The query string is built by urlencode, not by interpolation

        Nothing needs escaping while both values are ints - which is the point: a value that DOES is
        one caller away, and an f-string would have pasted it in raw.
        """
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'items': []})

        with patch(f'{MODULE_PATH}.get_current_month_boundaries', return_value=(MONTH_START, MONTH_END)):
            license_manager.get_license_usage(-1, 0)

        requested: str = license_manager.oc_connector.oc_get.call_args.args[0]

        assert requested == _usage_url(-1, 0, MONTH_START, MONTH_END)
        assert ' ' not in requested

    def test_non_2xx_raises_get_error(self, license_manager: OcLicenseManager) -> None:
        """A non-2xx response raises OcLicenseGetError."""
        license_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with patch(f'{MODULE_PATH}.get_current_month_boundaries', return_value=(MONTH_START, MONTH_END)):
            with pytest.raises(OcLicenseGetError):
                license_manager.get_license_usage()


# ---------------------------------------------- get_current_month_boundaries ---------------------------------------- #

@pytest.mark.usefixtures('berlin_timezone')
class TestGetCurrentMonthBoundaries:
    """
    ``get_current_month_boundaries`` answers the current month in epoch milliseconds

    A module-level function, not a method: it touches no manager state, so it is called directly here
    without an OpenCelium connector.
    """

    def test_a_mid_year_month(self) -> None:
        """
        For a mid-year date the bounds span the 1st 00:00 to the last whole second of that month

        The expected values are absolute constants for `Europe/Berlin`, so they are an assertion
        about the answer rather than a re-run of the code's own arithmetic.
        """
        with patch(f'{MODULE_PATH}.datetime', _frozen_datetime(datetime(2026, 3, 15, 10, 30))):
            start, end = get_current_month_boundaries()

        assert start == MARCH_2026_START_MS
        assert end == MARCH_2026_END_MS
        assert start < end

    def test_december_rolls_into_next_year(self) -> None:
        """In December the end bound rolls over into January of the next year."""
        with patch(f'{MODULE_PATH}.datetime', _frozen_datetime(datetime(2026, 12, 10))):
            start, end = get_current_month_boundaries()

        assert start == DECEMBER_2026_START_MS
        assert end == DECEMBER_2026_END_MS

    def test_the_window_is_the_hosts_local_month(self) -> None:
        """
        The month is the HOST's, not UTC's, and not the tenant's

        `2026-03-01 00:00` in Berlin is 23:00 on February 28th in UTC, so the window starts before
        the month does for anyone reading it in UTC - and a tenant further east is reported a month
        that is not theirs. Recorded as behaviour: discussion-backlog #225.
        """
        with patch(f'{MODULE_PATH}.datetime', _frozen_datetime(datetime(2026, 3, 15))):
            start, _ = get_current_month_boundaries()

        assert start == MARCH_2026_START_MS
        assert datetime.fromtimestamp(start / 1000, tz=timezone.utc).month == 2

    def test_the_window_ends_a_whole_second_before_the_month_does(self) -> None:
        """
        The last 999 ms of the month fall outside the window

        The end is computed as "the 1st of next month minus one second", in millisecond units - so
        anything OpenCelium recorded in that final second is not counted. The other half of #225.
        """
        with patch(f'{MODULE_PATH}.datetime', _frozen_datetime(datetime(2026, 3, 15))):
            _, end = get_current_month_boundaries()

        assert APRIL_2026_START_MS - end == MISSING_MONTH_TAIL_MS

    def test_a_month_containing_the_dst_switch_is_still_one_window(self) -> None:
        """
        March 2026 contains the CEST switch, and the two ends carry different UTC offsets

        Naive local arithmetic gets this right by accident - `timestamp()` resolves each end with the
        offset in force at that moment - so the window is 31 days minus the lost hour, minus the
        second above.
        """
        with patch(f'{MODULE_PATH}.datetime', _frozen_datetime(datetime(2026, 3, 15))):
            start, end = get_current_month_boundaries()

        one_hour_ms: int = 3_600_000
        thirty_one_days_ms: int = 31 * 24 * one_hour_ms

        assert end - start == thirty_one_days_ms - one_hour_ms - MISSING_MONTH_TAIL_MS
