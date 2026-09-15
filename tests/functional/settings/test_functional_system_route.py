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
Functional smoke for the ``/settings/system`` REST routes.

Covers the general system-information endpoint and the config-information endpoint, including the
section serialization (the harness itself runs config-less, so the sections are stubbed) and the
failure -> 500 mappings of both routes.
"""
from http import HTTPStatus
from types import SimpleNamespace

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
# -------------------------------------------------------------------------------------------------------------------- #

SYSTEM_ROUTES: str = 'cmdb.interface.rest_api.routes.settings_routes.system_routes'


class TestSystemInformation:
    """GET /settings/system/ returns basic DataGerry system information."""

    def test_returns_system_information(self, rest_api) -> None:
        """The response carries the expected system-information keys."""
        response = rest_api.get('/settings/system/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        for key in ('title', 'version', 'db_version', 'runtime', 'starting_parameters'):
            assert key in body

    def test_manager_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure obtaining the settings manager is reported as 500."""
        original = ManagerProvider.get_manager

        def _selective(manager_type, request_user):
            if manager_type == ManagerType.SETTINGS:
                raise RuntimeError('boom')
            return original(manager_type, request_user)

        monkeypatch.setattr(ManagerProvider, 'get_manager', _selective)

        assert rest_api.get('/settings/system/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestConfigInformation:
    """GET /settings/system/config/ returns the config-file information."""

    def test_returns_config_information(self, rest_api) -> None:
        """The response carries the config path key and a properties list.

        In config-less mode (the test harness) 'path' is None (regression for B7: the route used to
        read ssc.config_file directly, which is unset config-less -> AttributeError -> 500).
        """
        response = rest_api.get('/settings/system/config/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'path' in body
        assert isinstance(body['properties'], list)

    def test_sections_are_serialized_as_key_value_pairs(self, rest_api, monkeypatch) -> None:
        """Each config section is emitted as [name, [[key, value], ...]] in reader order."""
        reader = SimpleNamespace(
            config_file='/etc/cmdb.conf',
            get_sections=lambda: ['Database', 'WebServer'],
            get_all_values_from_section=lambda section: (
                {'host': 'localhost', 'port': '27017'} if section == 'Database' else {'port': '4000'}
            ),
        )
        monkeypatch.setattr(f'{SYSTEM_ROUTES}.SystemConfigReader', lambda *_a, **_k: reader)

        body = rest_api.get('/settings/system/config/').get_json()

        assert body['path'] == '/etc/cmdb.conf'
        assert body['properties'] == [
            ['Database', [['host', 'localhost'], ['port', '27017']]],
            ['WebServer', [['port', '4000']]],
        ]

    def test_reader_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure reading the configuration is reported as 500."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(f'{SYSTEM_ROUTES}.SystemConfigReader', _boom)

        assert rest_api.get('/settings/system/config/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
