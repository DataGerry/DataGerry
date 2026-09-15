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
Unit tests for cmdb.manager.open_celium_managers.oc_base_manager.OcBaseManager

OcApiConnector (the external OpenCelium HTTP client built in __init__) is patched at the module path
so no connector / config / HTTP is touched. Only the shared ``is_valid_response`` gate is exercised:
a 2xx status is valid, anything outside 200-299 is not (the boundary that every OcBaseManager
subclass relies on to decide success vs raising its OC error).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'


class _OcError(Exception):
    """A stand-in OpenCelium error class for the parse_response tests."""


def _response(status_code: int, payload: object = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response carrying a status code and JSON text."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='base_manager')
def fixture_base_manager() -> OcBaseManager:
    """An OcBaseManager with its OcApiConnector patched out (no HTTP client built)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcBaseManager(MagicMock(), 'db_test')


class TestIsValidResponse:
    """``is_valid_response`` is True only for a 2xx status code."""

    @pytest.mark.parametrize(
        'status_code, expected',
        [
            (200, True),
            (201, True),
            (299, True),
            (300, False),
            (199, False),
            (404, False),
            (500, False),
        ],
    )
    def test_status_code_boundaries(self, base_manager: OcBaseManager, status_code: int, expected: bool) -> None:
        """Status codes in 200-299 are valid; everything below 200 or 300+ is not."""
        assert base_manager.is_valid_response(_response(status_code)) is expected


class TestParseResponse:
    """``parse_response`` returns the parsed JSON body on a 2xx, else raises the given error."""

    def test_returns_parsed_json_on_success(self, base_manager: OcBaseManager) -> None:
        """A 2xx response body is returned as parsed JSON."""
        result = base_manager.parse_response(_response(200, {'a': 1}), _OcError, 'boom')

        assert result == {'a': 1}

    def test_returns_parsed_list_on_success(self, base_manager: OcBaseManager) -> None:
        """A 2xx response whose body is a JSON list is returned as a list."""
        result = base_manager.parse_response(_response(200, [{'a': 1}]), _OcError, 'boom')

        assert result == [{'a': 1}]

    def test_raises_error_cls_on_non_2xx(self, base_manager: OcBaseManager) -> None:
        """A non-2xx response raises the provided error class with the given message."""
        with pytest.raises(_OcError, match='boom'):
            base_manager.parse_response(_response(500), _OcError, 'boom')
