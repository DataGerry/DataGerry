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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'


def _response(status_code: int) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response carrying just a status code."""
    return SimpleNamespace(status_code=status_code)


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
