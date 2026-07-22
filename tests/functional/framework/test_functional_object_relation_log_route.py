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
Functional smoke for the ``/object_relation_logs`` REST routes

Covers the read-only + single-delete route contract: the list envelope, the single get, the 404 on
a missing id, the delete + 404-after-delete, the delete-missing 404, and the manager-error -> HTTP
status mapping. CmdbObjectRelationLogs have no public create route (they are written internally), so
the docs are seeded directly via the collection.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationLogsManager
from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction
from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerIterationError,
    ObjectRelationLogsManagerGetError,
    ObjectRelationLogsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/object_relation_logs'

AUTHOR_ID: int = 1
OBJECT_RELATION_ID: int = 540

LOG_ID_FOR_GET: int = 67101
LOG_ID_FOR_DELETE: int = 67102
MISSING_LOG_ID: int = 67900

ALL_LOG_IDS: list[int] = [LOG_ID_FOR_GET, LOG_ID_FOR_DELETE]


def _log_doc(public_id: int) -> dict[str, Any]:
    """Builds a CmdbObjectRelationLog document for direct collection seeding."""
    return {
        'public_id': public_id,
        'object_relation_id': OBJECT_RELATION_ID,
        'object_relation_parent_id': 1,
        'object_relation_child_id': 2,
        'action': LogInteraction.CREATE,
        'author_id': AUTHOR_ID,
        'author_name': 'admin',
        'changes': {},
    }


def _insert_log_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbObjectRelationLog doc directly via the collection."""
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .insert_one(_log_doc(public_id))


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_LOG_IDS}})


class TestGetObjectRelationLog:
    """GET /object_relation_logs/<id> and GET /object_relation_logs/ envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        _insert_log_doc(database_manager, database_name, LOG_ID_FOR_GET)
        yield
        database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
            .delete_one({'public_id': LOG_ID_FOR_GET})

    def test_get_single_returns_log(self, rest_api) -> None:
        """A known id returns 200 with the matching log."""
        response = rest_api.get(f'{ROUTE_URL}/{LOG_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == LOG_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /object_relation_logs/ returns a results envelope matching X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestDeleteObjectRelationLog:
    """DELETE /object_relation_logs/<id> removes a log."""

    def test_delete_removes_log(self, rest_api,
                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE removes the log and a subsequent GET returns 404."""
        _insert_log_doc(database_manager, database_name, LOG_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{LOG_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert rest_api.get(f'{ROUTE_URL}/{LOG_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
                .delete_one({'public_id': LOG_ID_FOR_DELETE})

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent log returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.NOT_FOUND


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationLogsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'iterate', _raise(ObjectRelationLogsManagerIterationError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationLogsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'get_object_relation_log',
            _raise(ObjectRelationLogsManagerGetError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationLogsManagerDeleteError (log found) surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'get_object_relation_log', lambda _self, _pid: _log_doc(MISSING_LOG_ID),
        )
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'delete_object_relation_log',
            _raise(ObjectRelationLogsManagerDeleteError('boom')),
        )

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LOG_ID}').status_code == HTTPStatus.BAD_REQUEST
