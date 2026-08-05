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
Functional smoke for the ``/date`` REST routes (DateSettings).

Covers the default GET (no stored section), the POST/PUT update, the update->GET round-trip that
previously crashed with a 500 because the stored '_id' could not be splatted back into
DateSettingsDAO, the empty-body 400 (which was previously masked as a 500), and the tolerance of an
'_id' carried in the request body.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

DATE_SECTION: str = 'date'
DATE_FORMAT: str = 'DD.MM.YYYY'
TIMEZONE: str = 'Europe/Berlin'


def _date_payload(date_format: str = DATE_FORMAT, timezone: str = TIMEZONE) -> dict[str, Any]:
    """Builds a DateSettings body accepted by POST / PUT."""
    return {'date_format': date_format, 'timezone': timezone}


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the 'date' settings section before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
            .delete_many({'_id': DATE_SECTION})

    _purge()
    yield
    _purge()


class TestGetDateSettings:
    """GET /date/ returns the date settings."""

    def test_returns_defaults_when_absent(self, rest_api) -> None:
        """With no stored section the defaults are returned."""
        response = rest_api.get('/date/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'date_format' in body
        assert 'timezone' in body


class TestUpdateDateSettings:
    """POST/PUT /date/ updates the date settings."""

    def test_post_updates_and_persists(self, rest_api) -> None:
        """A POST with a valid body succeeds and the values become retrievable."""
        response = rest_api.post('/date/', json=_date_payload())

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['date_format'] == DATE_FORMAT
        assert body['timezone'] == TIMEZONE

    def test_put_updates(self, rest_api) -> None:
        """PUT is accepted as well as POST for the update."""
        assert rest_api.put('/date/', json=_date_payload()).status_code == HTTPStatus.OK

    def test_update_then_get_round_trip(self, rest_api) -> None:
        """After an update the GET returns the stored values (general round-trip coverage)."""
        assert rest_api.post('/date/', json=_date_payload()).status_code == HTTPStatus.OK

        response = rest_api.get('/date/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['date_format'] == DATE_FORMAT
        assert body['timezone'] == TIMEZONE

    def test_body_with_id_is_tolerated(self, rest_api) -> None:
        """A body carrying extra keys such as '_id' is accepted (regression: previously 500).

        update_date_settings splats the raw request body into DateSettingsDAO; before build_date_settings
        an extra key like '_id' (e.g. echoed back by the frontend) raised TypeError -> masked as 500.
        """
        payload = _date_payload()
        payload['_id'] = DATE_SECTION

        assert rest_api.post('/date/', json=payload).status_code == HTTPStatus.OK

    def test_empty_body_returns_400(self, rest_api) -> None:
        """An empty body is rejected with 400 (regression: previously masked as 500)."""
        assert rest_api.post('/date/', json={}).status_code == HTTPStatus.BAD_REQUEST


class TestDateSettingsErrors:
    """The route handlers map unexpected manager failures to 500."""

    def test_get_manager_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while reading the section is reported as 500."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _boom)

        assert rest_api.get('/date/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_write_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while writing the section is reported as 500."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(SettingsManager, 'write', _boom)

        assert rest_api.post('/date/', json=_date_payload()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
