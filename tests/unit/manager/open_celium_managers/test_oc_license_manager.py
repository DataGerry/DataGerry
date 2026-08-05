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
Unit tests for cmdb.manager.open_celium_managers.oc_license_manager.OcLicenseManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each read test stubs oc_get with a fake response and asserts the
endpoint, the parsed 2xx body, and OcLicenseGetError on a non-2xx response. The month-boundary helper
(real date arithmetic) is tested deterministically by patching ``datetime.now`` while keeping the
``datetime`` constructor real. No HTTP, no Mongo.
"""
import json
from datetime import datetime, timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_license_manager import (
    OcLicenseManager,
    LICENSE_ACTIVATION_URL,
    ACTIVE_LICENSE_URL,
    LICENSE_USAGE_URL,
)
from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'
MODULE_PATH: str = 'cmdb.manager.open_celium_managers.oc_license_manager'

DEFAULT_PAGE: int = 0
DEFAULT_SIZE: int = 5
MONTH_START: int = 1_700_000_000_000
MONTH_END: int = 1_700_999_999_000

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='license_manager')
def fixture_license_manager() -> OcLicenseManager:
    """An OcLicenseManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcLicenseManager(MagicMock(), 'db_test')


# ------------------------------------------------- get_license_activation ------------------------------------------- #

class TestGetLicenseActivation:
    """``get_license_activation`` GETs the activation-request endpoint."""

    def test_gets_and_returns_body(self, license_manager: OcLicenseManager) -> None:
        """A 2xx body is parsed and returned from the activation endpoint."""
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'activation': 'blob'})

        result = license_manager.get_license_activation()

        assert result == {'activation': 'blob'}
        license_manager.oc_connector.oc_get.assert_called_once_with(LICENSE_ACTIVATION_URL)

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
        license_manager.get_current_month_boundaries = MagicMock(return_value=(MONTH_START, MONTH_END))
        license_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'items': []})

        result = license_manager.get_license_usage(DEFAULT_PAGE, DEFAULT_SIZE)

        assert result == {'items': []}
        license_manager.oc_connector.oc_get.assert_called_once_with(
            f"{LICENSE_USAGE_URL}?page={DEFAULT_PAGE}&size={DEFAULT_SIZE}&startDate={MONTH_START}&endDate={MONTH_END}"
        )

    def test_non_2xx_raises_get_error(self, license_manager: OcLicenseManager) -> None:
        """A non-2xx response raises OcLicenseGetError."""
        license_manager.get_current_month_boundaries = MagicMock(return_value=(MONTH_START, MONTH_END))
        license_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcLicenseGetError):
            license_manager.get_license_usage()


# ---------------------------------------------- get_current_month_boundaries ---------------------------------------- #

class TestGetCurrentMonthBounderies:
    """``get_current_month_boundaries`` returns the first-moment / last-moment of the current month (ms)."""

    def test_mid_year_month(self, license_manager: OcLicenseManager) -> None:
        """For a mid-year date the bounds span the 1st 00:00 to the last second of that month."""
        with patch(f'{MODULE_PATH}.datetime') as dt_mock:
            dt_mock.now.return_value = datetime(2026, 3, 15, 10, 30)
            dt_mock.side_effect = datetime

            start, end = license_manager.get_current_month_boundaries()

        assert start == int(datetime(2026, 3, 1).timestamp() * 1000)
        assert end == int((datetime(2026, 4, 1) - timedelta(seconds=1)).timestamp() * 1000)
        assert start < end

    def test_december_rolls_into_next_year(self, license_manager: OcLicenseManager) -> None:
        """In December the end bound rolls over into January of the next year."""
        with patch(f'{MODULE_PATH}.datetime') as dt_mock:
            dt_mock.now.return_value = datetime(2026, 12, 10)
            dt_mock.side_effect = datetime

            start, end = license_manager.get_current_month_boundaries()

        assert start == int(datetime(2026, 12, 1).timestamp() * 1000)
        assert end == int((datetime(2027, 1, 1) - timedelta(seconds=1)).timestamp() * 1000)
