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

Covers the default GET (no stored section), the POST/PUT update, the update->GET round-trip (the
stored '_id' must not be splatted back into DateSettingsDAO, or the read answers 500), the empty-body
400 (not masked as a 500), and the tolerance of an '_id' carried in the request body. The write's body is
held to DateSettingsDAO.SCHEMA (a refused body writes nothing); the read answers a missing or unusable stored
value as its default, and is open to a user without any system right while the write is not.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.models.group_model import USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

DATE_SECTION: str = 'date'
DATE_FORMAT: str = 'DD.MM.YYYY'
TIMEZONE: str = 'Europe/Berlin'
# A member of the predefined 'user' group, which holds no base.system right
PLAIN_USER_ID: int = 96951


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

    def test_answers_exactly_the_declared_shape(self, rest_api) -> None:
        """The read answers the stored settings as the section id, date format and timezone - nothing else"""
        rest_api.put('/date/', json=_date_payload())

        response = rest_api.get('/date/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'_id': DATE_SECTION, **_date_payload()}


class TestUpdateDateSettings:
    """POST/PUT /date/ updates the date settings."""

    def test_post_updates_and_persists(self, rest_api) -> None:
        """A POST with a valid body succeeds and the values become retrievable."""
        response = rest_api.post('/date/', json=_date_payload())

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['date_format'] == DATE_FORMAT
        assert body['timezone'] == TIMEZONE

    def test_write_stores_exactly_the_declared_document(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The stored section holds the section id, date format and timezone - and nothing else"""
        assert rest_api.put('/date/', json=_date_payload()).status_code == HTTPStatus.OK

        stored: dict[str, Any] = database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
            .find_one({'_id': DATE_SECTION})

        assert stored == {'_id': DATE_SECTION, **_date_payload()}

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
        """A body carrying extra keys such as '_id' is accepted, not answered with a 500.

        build_date_settings keeps only the declared keys, so an extra key like '_id' (e.g. echoed back by
        the frontend) is not splatted into DateSettingsDAO, where it would raise TypeError -> 500.
        """
        payload = _date_payload()
        payload['_id'] = DATE_SECTION

        assert rest_api.post('/date/', json=payload).status_code == HTTPStatus.OK

    def test_empty_body_returns_400(self, rest_api) -> None:
        """An empty body is rejected with 400, not masked as a 500."""
        assert rest_api.post('/date/', json={}).status_code == HTTPStatus.BAD_REQUEST


class TestUpdateBodyIsValidated:
    """POST / PUT /date/ hold the body to DateSettingsDAO.SCHEMA; a refused body writes nothing."""

    @staticmethod
    def _stored(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any] | None:
        """The stored date section, or None"""
        return database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
            .find_one({'_id': DATE_SECTION})

    @pytest.mark.parametrize('method', ['post', 'put'])
    @pytest.mark.parametrize('key', ['date_format', 'timezone'])
    def test_a_missing_key_is_a_400_naming_it(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str, method: str, key: str) -> None:
        """It used to reach a bare subscript and answer 500"""
        body: dict[str, Any] = _date_payload()
        body.pop(key)

        response = getattr(rest_api, method)('/date/', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert key in response.get_json()['message']
        assert self._stored(database_manager, database_name) is None

    @pytest.mark.parametrize('key', ['date_format', 'timezone'])
    @pytest.mark.parametrize('value', [None, '', 12, {'tz': 'UTC'}], ids=['null', 'empty', 'number', 'dict'])
    def test_a_value_that_is_no_non_empty_string_is_a_400(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str, key: str, value: Any) -> None:
        """It used to be stored and handed to the date pipe of every page"""
        response = rest_api.put('/date/', json={**_date_payload(), key: value})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert self._stored(database_manager, database_name) is None

    def test_a_refused_body_leaves_the_stored_settings_alone(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The section written before stays exactly as it was"""
        rest_api.put('/date/', json=_date_payload())

        assert rest_api.put('/date/', json={'date_format': ''}).status_code == HTTPStatus.BAD_REQUEST
        assert self._stored(database_manager, database_name) == {'_id': DATE_SECTION, **_date_payload()}

    def test_extra_keys_are_not_stored(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The validator drops what the schema does not declare"""
        assert rest_api.put('/date/', json={**_date_payload(), 'unexpected': 'value'}).status_code == HTTPStatus.OK
        assert self._stored(database_manager, database_name) == {'_id': DATE_SECTION, **_date_payload()}


class TestReadOfAStoredSection:
    """GET /date/ over a stored section the write's schema never saw"""

    @staticmethod
    def _store(database_manager: MongoDatabaseManager, database_name: str, document: dict[str, Any]) -> None:
        """Writes the date section directly, as an older version or a hand edit would"""
        database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
            .replace_one({'_id': DATE_SECTION}, {'_id': DATE_SECTION, **document}, upsert=True)

    def test_a_missing_key_is_answered_as_its_default(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The read every page makes used to answer 500 here"""
        self._store(database_manager, database_name, {'date_format': DATE_FORMAT})

        response = rest_api.get('/date/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'_id': DATE_SECTION, 'date_format': DATE_FORMAT,
                                       'timezone': DateSettingsDAO.__DEFAULT_SETTINGS__['timezone']}

    def test_an_unusable_value_is_answered_as_its_default(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A non-string or empty value stored before the schema existed"""
        self._store(database_manager, database_name, {'date_format': 12, 'timezone': ''})

        response = rest_api.get('/date/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'_id': DATE_SECTION, **DateSettingsDAO.__DEFAULT_SETTINGS__}

    def test_a_user_without_system_rights_may_read_but_not_write(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The read carries no right - the date pipe needs it for every account; the write needs system.edit"""
        self._store(database_manager, database_name, _date_payload())
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        users.delete_many({'public_id': PLAIN_USER_ID})
        users.insert_one({'public_id': PLAIN_USER_ID, 'user_name': f'user-{PLAIN_USER_ID}', 'active': True,
                          'group_id': USER_GROUP_ID, 'password': 'hashed-stub'})
        plain_user = SimpleNamespace(public_id=PLAIN_USER_ID)
        try:
            read = rest_api.get('/date/', user=plain_user)
            write = rest_api.put('/date/', json=_date_payload(timezone='UTC'), user=plain_user)

            assert read.status_code == HTTPStatus.OK
            assert read.get_json()['timezone'] == TIMEZONE
            assert write.status_code == HTTPStatus.FORBIDDEN
        finally:
            users.delete_many({'public_id': PLAIN_USER_ID})


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

    def test_get_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """
        The HTTPException arm hands an abort through with its own status

        Unreachable in a normal request - the read aborts nowhere inside its try - so it needs a
        forced abort. It exists so an abort added later is not swallowed by the generic handler and
        reported as a 500.
        """
        def _abort(*_args, **_kwargs):
            raise NotFound('forced')

        monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _abort)

        assert rest_api.get('/date/').status_code == HTTPStatus.NOT_FOUND

    def test_an_unacknowledged_write_is_a_400(self, rest_api, monkeypatch) -> None:
        """
        A write MongoDB did not acknowledge is refused rather than reported as success

        The route reads the section back and echoes it, so answering 200 here would return the
        settings the client sent while the stored ones are unchanged.
        """
        monkeypatch.setattr(SettingsManager, 'write', lambda *_a, **_k: SimpleNamespace(acknowledged=False))

        response = rest_api.post('/date/', json=_date_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'DateSettings' in response.get_json()['message']
