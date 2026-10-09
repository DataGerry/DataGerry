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
Functional tests for the single-log reads: a log looks the same wherever it is read, and only object logs are served

``GET /logs/<id>``, ``GET /logs/<id>/corresponding`` and ``DELETE /logs/<id>`` against the object-log lists. Pinned:

  - the single read answers exactly the row the list answers for the same log - a complete one, and an older one
    whose missing ``user_name`` / ``changes`` read ``'Unknown'`` / ``[]``, with a stale stored key left out
  - ``/corresponding`` answers its rows in that shape too
  - a document of another log kind with the id is a 404 on all three routes - as it is absent from every list - and
    the delete leaves it stored
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
# -------------------------------------------------------------------------------------------------------------------- #

LOGGED_OBJECT_ID: int = 89751
COMPLETE_LOG_ID: int = 89752
LEGACY_LOG_ID: int = 89753
OTHER_KIND_LOG_ID: int = 89754
ALL_LOG_IDS: list[int] = [COMPLETE_LOG_ID, LEGACY_LOG_ID, OTHER_KIND_LOG_ID]

OTHER_LOG_KIND: str = 'CmdbOtherLog'
STALE_KEY: str = 'legacy_key'


def _object_log(public_id: int, **overrides: Any) -> dict[str, Any]:
    """A stored edit log of the module's object"""
    return {
        'public_id': public_id, 'log_type': OBJECT_LOG_TYPE, 'object_id': LOGGED_OBJECT_ID, 'type_id': None,
        'action': 1, 'action_name': 'EDIT', 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin',
        'comment': 'edited', 'changes': {'old': [], 'new': []}, 'render_state': b'{"a": 1}', 'log_time': None,
        **overrides,
    }


@pytest.fixture(name='logs', autouse=True)
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """A complete object log, an older one, and a document of another kind; purged before and after"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})

    legacy: dict[str, Any] = _object_log(LEGACY_LOG_ID, **{STALE_KEY: 'x'})
    del legacy['user_name']
    del legacy['changes']

    logs.insert_many([
        _object_log(COMPLETE_LOG_ID),
        legacy,
        {'public_id': OTHER_KIND_LOG_ID, 'log_type': OTHER_LOG_KIND, 'object_id': LOGGED_OBJECT_ID, 'note': 'n'},
    ])
    yield logs
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})


def _list_rows(rest_api) -> dict[int, dict[str, Any]]:
    """The object's logs as the list answers them, by id"""
    response = rest_api.get(f'/logs/object/{LOGGED_OBJECT_ID}?limit=0')

    assert response.status_code == HTTPStatus.OK

    return {row['public_id']: row for row in response.get_json()['results']}


class TestOneShape:
    """The single read is the list row"""

    @pytest.mark.parametrize('public_id', [COMPLETE_LOG_ID, LEGACY_LOG_ID], ids=['complete', 'legacy'])
    def test_the_single_read_equals_the_list_row(self, rest_api, public_id: int) -> None:
        """Key for key, value for value"""
        response = rest_api.get(f'/logs/{public_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == _list_rows(rest_api)[public_id]

    def test_an_older_log_reads_with_the_model_defaults(self, rest_api) -> None:
        """What the log view shows for an entry written without them"""
        single: dict[str, Any] = rest_api.get(f'/logs/{LEGACY_LOG_ID}').get_json()

        assert single['user_name'] == CmdbObjectLog.UNKNOWN_USER_STRING
        assert single['changes'] == []

    def test_a_stale_stored_key_is_not_answered(self, rest_api, logs) -> None:
        """It stays in the database, out of the response"""
        assert STALE_KEY not in rest_api.get(f'/logs/{LEGACY_LOG_ID}').get_json()
        assert logs.find_one({'public_id': LEGACY_LOG_ID})[STALE_KEY] == 'x'

    def test_the_fields_the_log_view_reads_are_there(self, rest_api) -> None:
        """object-log.component reads public_id, version, user_name, comment and render_state"""
        single: dict[str, Any] = rest_api.get(f'/logs/{COMPLETE_LOG_ID}').get_json()

        assert {'public_id', 'version', 'user_name', 'comment', 'render_state'} <= set(single)

    def test_the_corresponding_rows_are_list_rows(self, rest_api) -> None:
        """The other edit log of the same object, in the same shape"""
        response = rest_api.get(f'/logs/{COMPLETE_LOG_ID}/corresponding')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == [_list_rows(rest_api)[LEGACY_LOG_ID]]


class TestOnlyObjectLogs:
    """A document of another kind is absent from the log routes"""

    def test_it_is_not_listed(self, rest_api) -> None:
        """The baseline the single reads now agree with"""
        assert OTHER_KIND_LOG_ID not in _list_rows(rest_api)

    @pytest.mark.parametrize('suffix', ['', '/corresponding'], ids=['single', 'corresponding'])
    def test_reading_it_is_a_404(self, rest_api, suffix: str) -> None:
        """Like a log that does not exist"""
        assert rest_api.get(f'/logs/{OTHER_KIND_LOG_ID}{suffix}').status_code == HTTPStatus.NOT_FOUND

    def test_deleting_it_is_a_404_and_leaves_it_stored(self, rest_api, logs) -> None:
        """The object-log delete does not reach it"""
        assert rest_api.delete(f'/logs/{OTHER_KIND_LOG_ID}').status_code == HTTPStatus.NOT_FOUND
        assert logs.count_documents({'public_id': OTHER_KIND_LOG_ID}) == 1
