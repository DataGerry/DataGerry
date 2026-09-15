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
Functional tests for the ``/logs`` REST routes

Covers the route-layer concerns: single read (hit + 404), the list endpoints (logs-by-object,
deleted-action logs, object-still-exists vs object-deleted via the framework.objects join),
corresponding-log lookup (returns the sibling edit, excludes self, 404 when the source log is
missing) and delete (success + 404 guard). The existing-object filtering is asserted against the
test's own seeded public_ids so it is robust to other logs already in the collection.
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LogsManager
from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerDeleteError,
)
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/logs'

OBJECT_LOG_TYPE: str = CmdbObjectLog.__name__

# Log public_ids (kept in a high, dedicated band to avoid collisions with seeded/admin logs)
LOG_ID_SINGLE: int = 90001
LOG_ID_EDIT_A: int = 90002
LOG_ID_EDIT_B: int = 90003
LOG_ID_DELETE_ACTION: int = 90004
LOG_ID_OBJECT_EXISTS: int = 90005
LOG_ID_OBJECT_DELETED: int = 90006
LOG_ID_FOR_DELETE: int = 90007
MISSING_LOG_ID: int = 90099

# Object public_ids referenced by the logs above
OBJECT_ID_WITH_EDITS: int = 90500
OBJECT_ID_FOR_DELETE_LOG: int = 90550
EXISTING_OBJECT_ID: int = 90600
DELETED_OBJECT_ID: int = 90700

# include_users feature: logs for a dedicated object, two seeded users + one deleted (unseeded) user
LOG_ID_IU_A: int = 90010
LOG_ID_IU_B: int = 90011
LOG_ID_IU_DUP: int = 90012
LOG_ID_IU_MISSING_USER: int = 90013
OBJECT_ID_IU: int = 90560
USER_ID_A: int = 90800
USER_ID_B: int = 90801
USER_ID_MISSING: int = 90899

MINIMAL_USER_FIELDS: set[str] = {'public_id', 'first_name', 'last_name', 'image', 'user_name'}

ALL_LOG_IDS: list[int] = [
    LOG_ID_SINGLE, LOG_ID_EDIT_A, LOG_ID_EDIT_B, LOG_ID_DELETE_ACTION,
    LOG_ID_OBJECT_EXISTS, LOG_ID_OBJECT_DELETED, LOG_ID_FOR_DELETE,
    LOG_ID_IU_A, LOG_ID_IU_B, LOG_ID_IU_DUP, LOG_ID_IU_MISSING_USER,
]
ALL_OBJECT_IDS: list[int] = [EXISTING_OBJECT_ID]
ALL_USER_IDS: list[int] = [USER_ID_A, USER_ID_B]


def _logs(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the logs collection handle."""
    return database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)


def _objects(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the objects collection handle."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _log_doc(public_id: int,
             object_id: int,
             action: LogAction = LogAction.EDIT,
             log_type: str = OBJECT_LOG_TYPE) -> dict[str, Any]:
    """Builds a CmdbObjectLog doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'log_type': log_type,
        'action': action.value,
        'action_name': action.name,
        'object_id': object_id,
        'version': '1.0.0',
        'user_id': 1,
        'user_name': 'admin',
        'changes': [],
        'comment': 'functional-test',
        'render_state': None,
    }


def _users(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the users collection handle."""
    return database_manager.get_collection(CmdbUser.COLLECTION, database_name)


def _iu_log_doc(public_id: int, user_id: int) -> dict[str, Any]:
    """Builds an object log referencing OBJECT_ID_IU with a specific user_id (include_users tests)."""
    doc = _log_doc(public_id, OBJECT_ID_IU)
    doc['user_id'] = user_id
    doc['user_name'] = f'stored-user-{user_id}'
    return doc


def _user_doc(public_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbUser doc for direct insertion."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'first_name': f'First{public_id}',
        'last_name': f'Last{public_id}',
        'image': None,
        'active': True,
    }


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes all seeded logs + helper objects + users after each test."""
    yield
    _logs(database_manager, database_name).delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    _objects(database_manager, database_name).delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    _users(database_manager, database_name).delete_many({'public_id': {'$in': ALL_USER_IDS}})


def _result_ids(payload: dict[str, Any]) -> set[int]:
    """Extracts the public_ids from a GetMultiResponse results envelope."""
    return {entry['public_id'] for entry in payload['results']}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    READ - SINGLE                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetSingle:
    """GET /logs/<id> returns the log or 404."""

    def test_get_single_returns_log(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A seeded log is returned by its public_id."""
        _logs(database_manager, database_name).insert_one(_log_doc(LOG_ID_SINGLE, OBJECT_ID_WITH_EDITS))

        response = rest_api.get(f'{ROUTE_URL}/{LOG_ID_SINGLE}')

        assert response.status_code == HTTPStatus.OK
        assert response.json['public_id'] == LOG_ID_SINGLE

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """An unknown public_id yields 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     READ - LISTS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetByObject:
    """GET /logs/object/<object_id> returns the object's logs."""

    def test_returns_only_logs_of_the_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Logs for the requested object are returned; logs for other objects are not."""
        _logs(database_manager, database_name).insert_many([
            _log_doc(LOG_ID_EDIT_A, OBJECT_ID_WITH_EDITS),
            _log_doc(LOG_ID_SINGLE, EXISTING_OBJECT_ID),
        ])

        response = rest_api.get(f'{ROUTE_URL}/object/{OBJECT_ID_WITH_EDITS}')

        assert response.status_code == HTTPStatus.OK
        ids = _result_ids(response.json)
        assert LOG_ID_EDIT_A in ids
        assert LOG_ID_SINGLE not in ids


class TestGetDeleteLogs:
    """GET /logs/object/deleted returns logs whose action is DELETE."""

    def test_returns_delete_action_logs(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE-action log is included while an EDIT-action log is not."""
        _logs(database_manager, database_name).insert_many([
            _log_doc(LOG_ID_DELETE_ACTION, OBJECT_ID_FOR_DELETE_LOG, action=LogAction.DELETE),
            _log_doc(LOG_ID_EDIT_A, OBJECT_ID_WITH_EDITS, action=LogAction.EDIT),
        ])

        response = rest_api.get(f'{ROUTE_URL}/object/deleted')

        assert response.status_code == HTTPStatus.OK
        ids = _result_ids(response.json)
        assert LOG_ID_DELETE_ACTION in ids
        assert LOG_ID_EDIT_A not in ids


class TestExistingVsDeletedObjects:
    """GET /logs/object/exists and /notexists split logs by whether the object still exists."""

    def test_existing_object_log_in_exists_not_in_notexists(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A log whose object still exists shows under /exists, not under /notexists."""
        _objects(database_manager, database_name).insert_one({'public_id': EXISTING_OBJECT_ID})
        _logs(database_manager, database_name).insert_one(
            _log_doc(LOG_ID_OBJECT_EXISTS, EXISTING_OBJECT_ID)
        )

        exists = rest_api.get(f'{ROUTE_URL}/object/exists')
        notexists = rest_api.get(f'{ROUTE_URL}/object/notexists')

        assert exists.status_code == HTTPStatus.OK
        assert notexists.status_code == HTTPStatus.OK
        assert LOG_ID_OBJECT_EXISTS in _result_ids(exists.json)
        assert LOG_ID_OBJECT_EXISTS not in _result_ids(notexists.json)

    def test_deleted_object_log_in_notexists_not_in_exists(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A log whose object is gone shows under /notexists, not under /exists."""
        _logs(database_manager, database_name).insert_one(
            _log_doc(LOG_ID_OBJECT_DELETED, DELETED_OBJECT_ID)
        )

        exists = rest_api.get(f'{ROUTE_URL}/object/exists')
        notexists = rest_api.get(f'{ROUTE_URL}/object/notexists')

        assert LOG_ID_OBJECT_DELETED in _result_ids(notexists.json)
        assert LOG_ID_OBJECT_DELETED not in _result_ids(exists.json)


class TestCorrespondingLog:
    """GET /logs/<id>/corresponding returns the object's other edit logs."""

    def test_returns_sibling_edit_excluding_self(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """For two edit logs on one object, requesting one returns the other and not itself."""
        _logs(database_manager, database_name).insert_many([
            _log_doc(LOG_ID_EDIT_A, OBJECT_ID_WITH_EDITS, action=LogAction.EDIT),
            _log_doc(LOG_ID_EDIT_B, OBJECT_ID_WITH_EDITS, action=LogAction.EDIT),
        ])

        response = rest_api.get(f'{ROUTE_URL}/{LOG_ID_EDIT_A}/corresponding')

        assert response.status_code == HTTPStatus.OK
        returned_ids = {entry['public_id'] for entry in response.json}
        assert LOG_ID_EDIT_B in returned_ids
        assert LOG_ID_EDIT_A not in returned_ids

    def test_missing_source_log_returns_404(self, rest_api) -> None:
        """Bug-fix guard: a missing source log yields 404, not a 500 from a None lookup."""
        assert rest_api.get(
            f'{ROUTE_URL}/{MISSING_LOG_ID}/corresponding'
        ).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDelete:
    """DELETE /logs/<id> removes the log or 404s when it does not exist."""

    def test_delete_removes_log(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A seeded log is deleted and no longer present in the collection."""
        _logs(database_manager, database_name).insert_one(_log_doc(LOG_ID_FOR_DELETE, OBJECT_ID_WITH_EDITS))

        response = rest_api.delete(f'{ROUTE_URL}/{LOG_ID_FOR_DELETE}')

        assert response.status_code == HTTPStatus.OK
        assert _logs(database_manager, database_name).find_one({'public_id': LOG_ID_FOR_DELETE}) is None

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Bug-fix guard: deleting an unknown log yields 404 instead of a success-shaped response."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                              INCLUDE USERS (?include_users)                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIncludeUsers:
    """``?include_users=true`` nests ``results`` as ``{logs, users}`` with the referenced users resolved.

    Uses the by-object list route for isolation: only the seeded OBJECT_ID_IU logs are returned, so the
    resolved ``users`` map is exactly the users those logs reference.
    """

    def _seed_iu_logs(self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Seeds three logs for two users (one duplicated) + one log for a user that does not exist."""
        _logs(database_manager, database_name).insert_many([
            _iu_log_doc(LOG_ID_IU_A, USER_ID_A),
            _iu_log_doc(LOG_ID_IU_B, USER_ID_B),
            _iu_log_doc(LOG_ID_IU_DUP, USER_ID_A),
            _iu_log_doc(LOG_ID_IU_MISSING_USER, USER_ID_MISSING),
        ])
        _users(database_manager, database_name).insert_many([_user_doc(USER_ID_A), _user_doc(USER_ID_B)])

    def test_default_results_is_a_plain_log_list(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Without the flag, results stays the plain list of logs (unchanged default)."""
        self._seed_iu_logs(database_manager, database_name)

        response = rest_api.get(f'{ROUTE_URL}/object/{OBJECT_ID_IU}')

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json()['results'], list)

    def test_include_users_nests_logs_and_users(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """With the flag, results becomes {logs, users}; users is keyed by public_id with minimal fields."""
        self._seed_iu_logs(database_manager, database_name)

        response = rest_api.get(f'{ROUTE_URL}/object/{OBJECT_ID_IU}?include_users=true')

        assert response.status_code == HTTPStatus.OK
        results = response.get_json()['results']
        assert set(results) == {'logs', 'users'}
        assert isinstance(results['logs'], list)

        users_map = results['users']
        # both referenced (existing) users are resolved, keyed by stringified public_id, deduped
        assert set(users_map) == {str(USER_ID_A), str(USER_ID_B)}
        user_a = users_map[str(USER_ID_A)]
        assert user_a['public_id'] == USER_ID_A
        # only the minimal fields are exposed (no password / group_id / etc.)
        assert set(user_a) == MINIMAL_USER_FIELDS

    def test_include_users_omits_deleted_user(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A log whose user_id has no matching user is omitted from the users map."""
        self._seed_iu_logs(database_manager, database_name)

        response = rest_api.get(f'{ROUTE_URL}/object/{OBJECT_ID_IU}?include_users=true')

        users_map = response.get_json()['results']['users']
        assert str(USER_ID_MISSING) not in users_map


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc

    return _fail


def _abort_418(*_args, **_kwargs):
    """Aborts with a status no handler maps, proving HTTPExceptions pass through untouched."""
    abort(HTTPStatus.IM_A_TEAPOT)


class TestCorrespondingLogWithoutObject:
    """A log that does not belong to an object cannot have corresponding object logs."""

    NON_OBJECT_LOG_ID: int = 90020

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a log document that carries no object_id (the collection is shared by log_type)."""
        doc = _log_doc(self.NON_OBJECT_LOG_ID, OBJECT_ID_WITH_EDITS)
        del doc['object_id']
        _logs(database_manager, database_name).insert_one(doc)
        yield
        _logs(database_manager, database_name).delete_one({'public_id': self.NON_OBJECT_LOG_ID})

    def test_returns_400_instead_of_500(self, rest_api) -> None:
        """The missing key used to raise a KeyError into the catch-all and answer 500 (regression)."""
        response = rest_api.get(f'{ROUTE_URL}/{self.NON_OBJECT_LOG_ID}/corresponding')

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestErrorMapping:
    """Every handler maps its manager failures to the documented status codes."""

    LIST_URLS: list[str] = [
        f'{ROUTE_URL}/object/exists',
        f'{ROUTE_URL}/object/notexists',
        f'{ROUTE_URL}/object/deleted',
        f'{ROUTE_URL}/object/{OBJECT_ID_WITH_EDITS}',
    ]

    # ---- single read ---- #
    def test_single_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerGetError on the single read maps to 400."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(BaseManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on the single read maps to 500."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- lists ---- #
    @pytest.mark.parametrize('url', LIST_URLS, ids=['exists', 'notexists', 'deleted', 'by-object'])
    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch, url: str) -> None:
        """A BaseManagerIterationError maps every list route to 400."""
        monkeypatch.setattr(LogsManager, 'iterate', _raiser(BaseManagerIterationError('boom')))

        assert rest_api.get(url).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('url', LIST_URLS, ids=['exists', 'notexists', 'deleted', 'by-object'])
    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch, url: str) -> None:
        """An unexpected error maps every list route to 500."""
        monkeypatch.setattr(LogsManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(url).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize('url', LIST_URLS, ids=['exists', 'notexists', 'deleted', 'by-object'])
    def test_list_passes_an_http_exception_through(self, rest_api, monkeypatch, url: str) -> None:
        """An HTTPException raised inside a list handler keeps its own status (regression)."""
        monkeypatch.setattr(LogsManager, 'iterate', _abort_418)

        assert rest_api.get(url).status_code == HTTPStatus.IM_A_TEAPOT

    # ---- corresponding ---- #
    def test_corresponding_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerGetError while reading the source log maps to 400."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(BaseManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}/corresponding').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_corresponding_iteration_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A BaseManagerIterationError while collecting the siblings maps to 400."""
        _logs(database_manager, database_name).insert_one(_log_doc(LOG_ID_SINGLE, OBJECT_ID_WITH_EDITS))
        monkeypatch.setattr(LogsManager, 'iterate', _raiser(BaseManagerIterationError('boom')))
        try:
            assert rest_api.get(f'{ROUTE_URL}/{LOG_ID_SINGLE}/corresponding').status_code \
                == HTTPStatus.BAD_REQUEST
        finally:
            _logs(database_manager, database_name).delete_one({'public_id': LOG_ID_SINGLE})

    def test_corresponding_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the corresponding route to 500."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}/corresponding').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- delete ---- #
    def test_delete_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerGetError while reading the log to delete maps to 400."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(BaseManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A BaseManagerDeleteError maps the delete to 400."""
        _logs(database_manager, database_name).insert_one(_log_doc(LOG_ID_FOR_DELETE, OBJECT_ID_WITH_EDITS))
        monkeypatch.setattr(LogsManager, 'delete', _raiser(BaseManagerDeleteError('boom')))
        try:
            assert rest_api.delete(f'{ROUTE_URL}/{LOG_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
        finally:
            _logs(database_manager, database_name).delete_one({'public_id': LOG_ID_FOR_DELETE})

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the delete to 500."""
        monkeypatch.setattr(LogsManager, 'get_one', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestDeleteResponseShape:
    """The delete route answers with the manager's boolean acknowledgement, not a count."""

    def test_returns_true(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A deleted log is reported as `true` (documented as a boolean, not a delete count)."""
        _logs(database_manager, database_name).insert_one(_log_doc(LOG_ID_FOR_DELETE, OBJECT_ID_WITH_EDITS))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{LOG_ID_FOR_DELETE}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() is True
        finally:
            _logs(database_manager, database_name).delete_one({'public_id': LOG_ID_FOR_DELETE})
