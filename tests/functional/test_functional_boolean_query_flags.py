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
Functional coverage for the boolean query flags that used to have rules of their own

Every flag is read by the API's one rule (``routes_helper.read_boolean_query_param`` / ``read_boolean_value``):
``true`` / ``false`` in any casing, absent is the flag's default, anything else a 400 naming the flag. Each of
these flags used to default silently on a value it did not recognise. Per route: the value the frontend sends is
still read, and an unrecognised one is refused. ``copy_cma`` (the risk-assessment duplicate) is pinned with the
duplicate's own tests, which build the payload it needs; ``only_unmounted`` with the rack picker's
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
# -------------------------------------------------------------------------------------------------------------------- #

# Values no flag accepts any more - each used to read as the flag's default (or False)
UNRECOGNISED_VALUES: list[str] = ['1', 'yes', 'undefined']

# A public_id no object carries - the CI Explorer answers for it only AFTER reading its flags
MISSING_OBJECT_ID: int = 987654


def _assert_refused(response: Any, flag: str) -> None:
    """The flag's 400, naming it"""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert flag in response.get_json()['message']


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every feature licensed, so the gated routes (DocAPI, the CI Explorer's port source) are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


class TestOnlyActiveObjects:
    """``?onlyActiveObjCookie=`` on the object list - the frontend sends its toggle cookie: true or false"""

    @pytest.mark.parametrize('value', ['true', 'false'])
    def test_the_frontends_value_is_read(self, rest_api, value: str) -> None:
        """The two values the cookie holds"""
        assert rest_api.get(f'/objects/?onlyActiveObjCookie={value}').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('value', UNRECOGNISED_VALUES)
    def test_an_unrecognised_value_is_refused(self, rest_api, value: str) -> None:
        """It used to read as False - inactive objects listed silently"""
        _assert_refused(rest_api.get(f'/objects/?onlyActiveObjCookie={value}'), 'onlyActiveObjCookie')


class TestIncludeUsers:
    """``?include_users=`` on a log list - the frontend sends true"""

    def test_the_frontends_value_is_read(self, rest_api) -> None:
        """What log.service.ts sends"""
        assert rest_api.get(f'/logs/object/{MISSING_OBJECT_ID}?include_users=true').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('value', UNRECOGNISED_VALUES)
    def test_an_unrecognised_value_is_refused(self, rest_api, value: str) -> None:
        """It used to read as False"""
        _assert_refused(rest_api.get(f'/logs/object/{MISSING_OBJECT_ID}?include_users={value}'), 'include_users')


class TestAvailableSpecialTypes:
    """``?available=`` on the special-type list (no frontend sender)"""

    def test_true_is_read(self, rest_api) -> None:
        """The unused special types"""
        assert rest_api.get('/special_types/?available=true').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('value', UNRECOGNISED_VALUES)
    def test_an_unrecognised_value_is_refused_not_answered_500(self, rest_api, value: str) -> None:
        """Read ahead of the route's catch-all, which would have turned the 400 into a 500"""
        _assert_refused(rest_api.get(f'/special_types/?available={value}'), 'available')


class TestMinimalDocapiTemplates:
    """``?minimal=`` on the template list by filter - the frontend sends String(bool)"""

    URL: str = f'/docapi/template/by/{json.dumps({})}'

    @pytest.mark.parametrize('value', ['true', 'false'])
    def test_the_frontends_value_is_read(self, rest_api, value: str) -> None:
        """docapi.service.ts sends String(minimal)"""
        assert rest_api.get(f'{self.URL}?minimal={value}').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('value', UNRECOGNISED_VALUES)
    def test_an_unrecognised_value_is_refused(self, rest_api, value: str) -> None:
        """It used to read as False"""
        _assert_refused(rest_api.get(f'{self.URL}?minimal={value}'), 'minimal')


class TestCiExplorerScope:
    """The CI Explorer's four flags - the frontend sends literals and typed booleans"""

    FLAGS: list[str] = ['with_root', 'with_locations', 'with_ipam_relations', 'with_port_connections']

    @pytest.mark.parametrize('flag', FLAGS)
    def test_the_frontends_value_is_read(self, rest_api, flag: str) -> None:
        """Past the flags: the missing target is the answer, not the flag"""
        response = rest_api.get(f'/ci_explorer/items?target_id={MISSING_OBJECT_ID}&{flag}=false')

        assert response.status_code != HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('flag', FLAGS)
    def test_an_unrecognised_value_is_refused(self, rest_api, flag: str) -> None:
        """with_locations=1 used to turn locations OFF, though its default is on"""
        _assert_refused(rest_api.get(f'/ci_explorer/items?target_id={MISSING_OBJECT_ID}&{flag}=1'), flag)


class TestZipExport:
    """``zip`` on the object export - the frontend sends a boolean"""

    @pytest.mark.parametrize('value', UNRECOGNISED_VALUES)
    def test_an_unrecognised_value_is_refused(self, rest_api, value: str) -> None:
        """It used to export without the ZIP wrapper silently"""
        response = rest_api.get('/exporter/', query_string={
            'filter': json.dumps({'public_id': MISSING_OBJECT_ID}), 'classname': 'CsvExportFormat', 'zip': value,
        })

        _assert_refused(response, 'zip')

