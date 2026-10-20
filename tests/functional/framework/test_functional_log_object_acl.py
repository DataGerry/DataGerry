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
Functional tests for the object-log read rule: a log is read through the type ACL of the object it records

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type and a HIDDEN one only the admin group may read), with
the seed's editor group given the two log rights - the reader every default user is, since the default ``user``
group holds ``base.framework.log.view``. Pinned, for that reader:

  - ``/logs/object/<id>`` of an existing object it may not read is a 403, like the object itself; of a deleted
    object, the logs are judged one by one by their stamped type
  - the three collection-wide lists (``exists`` / ``notexists`` / ``deleted``) leave every hidden log out
  - a single read, ``/corresponding`` and the delete of a hidden log are a 403, and the delete removes nothing
  - everything readable answers as before, and the admin still reads every log
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.manager import ObjectsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LOG_ACCESS_DENIED_MSG,
    OBJECT_LOGS_ACCESS_DENIED_MSG,
    LogRight,
)
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

GONE_OBJECT_ID: int = 89591

VISIBLE_LOG_ID: int = 89601
VISIBLE_SIBLING_LOG_ID: int = 89602
HIDDEN_LOG_ID: int = 89603
HIDDEN_SIBLING_LOG_ID: int = 89604
GONE_VISIBLE_LOG_ID: int = 89605
GONE_HIDDEN_LOG_ID: int = 89606
GONE_VISIBLE_DELETE_LOG_ID: int = 89607
GONE_HIDDEN_DELETE_LOG_ID: int = 89608
ALL_LOG_IDS: list[int] = [
    VISIBLE_LOG_ID, VISIBLE_SIBLING_LOG_ID, HIDDEN_LOG_ID, HIDDEN_SIBLING_LOG_ID,
    GONE_VISIBLE_LOG_ID, GONE_HIDDEN_LOG_ID, GONE_VISIBLE_DELETE_LOG_ID, GONE_HIDDEN_DELETE_LOG_ID,
]
HIDDEN_LOG_IDS: set[int] = {HIDDEN_LOG_ID, HIDDEN_SIBLING_LOG_ID, GONE_HIDDEN_LOG_ID, GONE_HIDDEN_DELETE_LOG_ID}

EDIT_ACTION: tuple[int, str] = (1, 'EDIT')
DELETE_ACTION: tuple[int, str] = (3, 'DELETE')
HIDDEN_VALUE: str = 'hidden-log-value'


def _log(public_id: int, object_id: int, type_id: int, action: tuple[int, str] = EDIT_ACTION) -> dict[str, Any]:
    """A stored object log, stamped with its object's type; a hidden one records the value the reader must not see"""
    changes: Any = []

    if type_id == seed.HIDDEN_TYPE_ID:
        changes = {'old': [], 'new': [{'name': seed.NAME_FIELD, 'value': HIDDEN_VALUE}]}

    return {
        'public_id': public_id, 'log_type': OBJECT_LOG_TYPE, 'object_id': object_id, 'type_id': type_id,
        'action': action[0], 'action_name': action[1], 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin',
        'comment': '', 'changes': changes, 'render_state': b'{}', 'log_time': None,
    }


@pytest.fixture(name='logs', autouse=True)
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The location ACL seed, its editor given the log rights, and one log per case"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    log_rights: list[str] = [LogRight.VIEW.value, LogRight.DELETE.value]
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': {'$each': log_rights}}},
    )
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    logs.insert_many([
        _log(VISIBLE_LOG_ID, seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID),
        _log(VISIBLE_SIBLING_LOG_ID, seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID),
        _log(HIDDEN_LOG_ID, seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID),
        _log(HIDDEN_SIBLING_LOG_ID, seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID),
        _log(GONE_VISIBLE_LOG_ID, GONE_OBJECT_ID, seed.VISIBLE_TYPE_ID),
        _log(GONE_HIDDEN_LOG_ID, GONE_OBJECT_ID, seed.HIDDEN_TYPE_ID),
        _log(GONE_VISIBLE_DELETE_LOG_ID, GONE_OBJECT_ID, seed.VISIBLE_TYPE_ID, DELETE_ACTION),
        _log(GONE_HIDDEN_DELETE_LOG_ID, GONE_OBJECT_ID, seed.HIDDEN_TYPE_ID, DELETE_ACTION),
    ])
    yield logs
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    seed.purge(database_manager, database_name)


def _reader() -> dict[str, Any]:
    """The request kwargs that send it as the log reader"""
    return {'user': seed.location_editor()}


def _listed_ids(response: Any) -> set[int]:
    """The seeded log ids a list answered"""
    assert response.status_code == HTTPStatus.OK

    return {log['public_id'] for log in response.get_json()['results']} & set(ALL_LOG_IDS)


class TestTheObjectsLogs:
    """GET /logs/object/<object_id>"""

    def test_an_object_the_reader_may_not_read_is_a_403(self, rest_api) -> None:
        """Like GET /objects/<id> - and its logs are not in the body"""
        response = rest_api.get(f'/logs/object/{seed.HIDDEN_ID}', **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_LOGS_ACCESS_DENIED_MSG.format(object_id=seed.HIDDEN_ID)
        assert HIDDEN_VALUE not in response.get_data(as_text=True)

    def test_a_readable_object_answers_its_logs(self, rest_api) -> None:
        """Unchanged"""
        response = rest_api.get(f'/logs/object/{seed.VISIBLE_ID}', **_reader())

        assert _listed_ids(response) == {VISIBLE_LOG_ID, VISIBLE_SIBLING_LOG_ID}

    def test_a_deleted_object_answers_only_the_logs_of_readable_types(self, rest_api) -> None:
        """No object to refuse - each log is judged by its stamped type, and the total follows"""
        response = rest_api.get(f'/logs/object/{GONE_OBJECT_ID}', **_reader())

        assert _listed_ids(response) == {GONE_VISIBLE_LOG_ID, GONE_VISIBLE_DELETE_LOG_ID}
        assert response.get_json()['total'] == 2

    def test_a_failed_object_read_is_a_400(self, rest_api, monkeypatch) -> None:
        """The object read is part of the decision - its failure is named, not a 500"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise ObjectsManagerGetError('down')

        monkeypatch.setattr(ObjectsManager, 'get_object', _fail)

        response = rest_api.get(f'/logs/object/{seed.VISIBLE_ID}', **_reader())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_admin_reads_the_hidden_object_logs(self, rest_api) -> None:
        """The HIDDEN type grants the admin group"""
        response = rest_api.get(f'/logs/object/{seed.HIDDEN_ID}')

        assert _listed_ids(response) == {HIDDEN_LOG_ID, HIDDEN_SIBLING_LOG_ID}


class TestTheCollectionWideLists:
    """The log settings screens: every hidden log is left out"""

    @pytest.mark.parametrize('route, readable', [
        ('exists', {VISIBLE_LOG_ID, VISIBLE_SIBLING_LOG_ID}),
        ('notexists', {GONE_VISIBLE_LOG_ID}),
        ('deleted', {GONE_VISIBLE_DELETE_LOG_ID}),
    ])
    def test_the_reader_sees_only_readable_types(self, rest_api, route: str, readable: set[int]) -> None:
        """Paged with a limit far above the seed, so every seeded log of the split is on the page"""
        response = rest_api.get(f'/logs/object/{route}?limit=0', **_reader())

        assert _listed_ids(response) == readable
        assert HIDDEN_VALUE not in response.get_data(as_text=True)

    @pytest.mark.parametrize('route, hidden', [
        ('exists', {HIDDEN_LOG_ID, HIDDEN_SIBLING_LOG_ID}),
        ('notexists', {GONE_HIDDEN_LOG_ID}),
        ('deleted', {GONE_HIDDEN_DELETE_LOG_ID}),
    ])
    def test_the_admin_still_sees_them(self, rest_api, route: str, hidden: set[int]) -> None:
        """Nothing changes for a caller the type grants"""
        assert hidden <= _listed_ids(rest_api.get(f'/logs/object/{route}?limit=0'))


class TestASingleLog:
    """GET /logs/<id>, GET /logs/<id>/corresponding and DELETE /logs/<id>"""

    def test_a_hidden_log_is_a_403(self, rest_api) -> None:
        """Its values are not in the body"""
        response = rest_api.get(f'/logs/{HIDDEN_LOG_ID}', **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == LOG_ACCESS_DENIED_MSG.format(public_id=HIDDEN_LOG_ID)
        assert HIDDEN_VALUE not in response.get_data(as_text=True)

    def test_a_hidden_log_of_a_deleted_object_is_a_403(self, rest_api) -> None:
        """Judged by the stamped type alone"""
        assert rest_api.get(f'/logs/{GONE_HIDDEN_LOG_ID}', **_reader()).status_code == HTTPStatus.FORBIDDEN

    def test_a_readable_log_answers(self, rest_api) -> None:
        """Unchanged"""
        response = rest_api.get(f'/logs/{VISIBLE_LOG_ID}', **_reader())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['public_id'] == VISIBLE_LOG_ID

    def test_the_siblings_of_a_hidden_log_are_a_403(self, rest_api) -> None:
        """The source log is judged first"""
        response = rest_api.get(f'/logs/{HIDDEN_LOG_ID}/corresponding', **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert HIDDEN_VALUE not in response.get_data(as_text=True)

    def test_the_siblings_of_a_readable_log_answer(self, rest_api) -> None:
        """The other edit log of the same object"""
        response = rest_api.get(f'/logs/{VISIBLE_LOG_ID}/corresponding', **_reader())

        assert response.status_code == HTTPStatus.OK
        assert [log['public_id'] for log in response.get_json()] == [VISIBLE_SIBLING_LOG_ID]

    def test_deleting_a_hidden_log_is_a_403_and_removes_nothing(self, rest_api, logs) -> None:
        """Whoever may not see a history may not erase it"""
        response = rest_api.delete(f'/logs/{HIDDEN_LOG_ID}', **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert logs.count_documents({'public_id': HIDDEN_LOG_ID}) == 1

    def test_deleting_a_readable_log_still_works(self, rest_api, logs) -> None:
        """Unchanged"""
        response = rest_api.delete(f'/logs/{VISIBLE_LOG_ID}', **_reader())

        assert response.status_code == HTTPStatus.OK
        assert logs.count_documents({'public_id': VISIBLE_LOG_ID}) == 0
