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
Functional tests for the object-relation history read rule: a CmdbObjectRelationLog is as readable as the relation
it records - readable while the caller may read the objects at both of its ends

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type, a PLAIN one, and a HIDDEN one only the admin group
may read) and five logs: VISIBLE->PLAIN (readable), VISIBLE->HIDDEN, HIDDEN->VISIBLE, one whose types could not be
recovered (null) and one written before the stamp (no keys). The seed's editor group is the caller, given both log
rights. Pinned, for that caller:

  - the list leaves the hidden logs out and counts only the readable ones - also under the frontend's pipeline
    filter, whose ``$addFields`` cannot forge the type ids because the rule runs ahead of it
  - a single read of a hidden log is a 403 naming it; a null-stamped or unstamped log is readable
  - a delete of a hidden log is a 403 and deletes nothing; a readable one is deleted and answered
  - a failed type-ACL read is a 400 on all three routes, never "nothing denied"
  - the admin, who may read every type, reads and lists every log as before
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.interface.rest_api.routes.relation_routes import relations_helper
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE,
    ObjectRelationLogRight,
)
from cmdb.errors.manager import BaseManagerGetError
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

LIST_URL: str = '/object_relation_logs/'
SINGLE_URL: str = '/object_relation_logs/{public_id}'

READABLE_LOG_ID: int = 89861       # VISIBLE -> PLAIN
HIDDEN_CHILD_LOG_ID: int = 89862   # VISIBLE -> HIDDEN
HIDDEN_PARENT_LOG_ID: int = 89863  # HIDDEN -> VISIBLE
NULL_LOG_ID: int = 89864           # types not recoverable
UNSTAMPED_LOG_ID: int = 89865      # written before the stamp
ALL_LOG_IDS: list[int] = [READABLE_LOG_ID, HIDDEN_CHILD_LOG_ID, HIDDEN_PARENT_LOG_ID, NULL_LOG_ID, UNSTAMPED_LOG_ID]
HIDDEN_LOG_IDS: list[int] = [HIDDEN_CHILD_LOG_ID, HIDDEN_PARENT_LOG_ID]
READABLE_LOG_IDS: list[int] = [READABLE_LOG_ID, NULL_LOG_ID, UNSTAMPED_LOG_ID]

LOG_RIGHTS: list[str] = [ObjectRelationLogRight.VIEW.value, ObjectRelationLogRight.DELETE.value]

ENDS: dict[int, tuple[tuple[int, Any], tuple[int, Any]]] = {
    READABLE_LOG_ID: ((seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID), (seed.PLAIN_ID, seed.PLAIN_TYPE_ID)),
    HIDDEN_CHILD_LOG_ID: ((seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID), (seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID)),
    HIDDEN_PARENT_LOG_ID: ((seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID), (seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID)),
    NULL_LOG_ID: ((seed.HIDDEN_ID, None), (seed.VISIBLE_ID, None)),
}


def _log(public_id: int) -> dict[str, Any]:
    """The stored relation log of the given id, stamped with its ends' types (none for the unstamped one)"""
    document: dict[str, Any] = {
        'public_id': public_id, 'object_relation_id': public_id, 'action': 'CREATE', 'author_id': seed.EDITOR_ID,
        'author_name': seed.EDITOR_NAME, 'changes': {'port': 'secret'},
        'object_relation_parent_id': seed.HIDDEN_ID, 'object_relation_child_id': seed.VISIBLE_ID,
    }

    if public_id in ENDS:
        parent, child = ENDS[public_id]
        document.update({
            'object_relation_parent_id': parent[0], 'relation_parent_type_id': parent[1],
            'object_relation_child_id': child[0], 'relation_child_type_id': child[1],
        })

    return document


@pytest.fixture(name='logs', autouse=True)
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The ACL seed, its editor given both log rights, and the five logs"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': {'$each': LOG_RIGHTS}}},
    )
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    logs.insert_many([_log(public_id) for public_id in ALL_LOG_IDS])
    yield logs
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    seed.purge(database_manager, database_name)


def _caller() -> dict[str, Any]:
    """The request kwargs that send the seed's editor"""
    return {'user': seed.location_editor()}


def _stored_ids(logs: Any) -> set[int]:
    """The seeded logs still stored"""
    return {document['public_id'] for document in logs.find({'public_id': {'$in': ALL_LOG_IDS}})}


def _listed(rest_api: Any, criteria: Any, **kwargs: Any) -> tuple[list[int], int]:
    """The listed seeded log ids and the total, under the given filter"""
    response = rest_api.get(LIST_URL, query_string={'filter': json.dumps(criteria), 'limit': 0}, **kwargs)

    assert response.status_code == HTTPStatus.OK
    return sorted(log['public_id'] for log in response.get_json()['results']), int(response.headers['X-Total-Count'])


def _fail(*_args: Any, **_kwargs: Any) -> None:
    """Stands in for a type-ACL read that fails"""
    raise BaseManagerGetError('read failed')


class TestList:
    """GET /object_relation_logs/ lists only the logs the caller can see"""

    def test_hidden_logs_are_left_out_and_not_counted(self, rest_api) -> None:
        """Hidden at either end is enough; null and unstamped stay readable"""
        assert _listed(rest_api, {'public_id': {'$in': ALL_LOG_IDS}}, **_caller()) == (READABLE_LOG_IDS, 3)

    def test_the_frontends_pipeline_cannot_forge_the_types(self, rest_api) -> None:
        """The rule runs ahead of the client's stages, so an $addFields overwriting the types changes nothing"""
        pipeline: list[dict[str, Any]] = [
            {'$match': {'$or': [{'object_relation_parent_id': seed.VISIBLE_ID},
                                {'object_relation_child_id': seed.VISIBLE_ID}]}},
            {'$addFields': {'relation_parent_type_id': seed.VISIBLE_TYPE_ID,
                            'relation_child_type_id': seed.VISIBLE_TYPE_ID}},
            {'$match': {'public_id': {'$in': ALL_LOG_IDS}}},
        ]

        assert _listed(rest_api, pipeline, **_caller()) == (READABLE_LOG_IDS, 3)

    def test_the_admin_lists_every_log(self, rest_api) -> None:
        """Nothing is denied to the admin group"""
        assert _listed(rest_api, {'public_id': {'$in': ALL_LOG_IDS}}) == (sorted(ALL_LOG_IDS), len(ALL_LOG_IDS))


class TestSingleRead:
    """GET /object_relation_logs/<id> answers only a log the caller can see"""

    @pytest.mark.parametrize('public_id', HIDDEN_LOG_IDS, ids=['hidden-child', 'hidden-parent'])
    def test_a_hidden_log_is_a_403_naming_it(self, rest_api, public_id: int) -> None:
        """Its values and its two object ids stay unread"""
        response = rest_api.get(SINGLE_URL.format(public_id=public_id), **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE.format(public_id=public_id)

    @pytest.mark.parametrize('public_id', READABLE_LOG_IDS, ids=['readable', 'null-stamped', 'unstamped'])
    def test_a_readable_log_is_answered(self, rest_api, public_id: int) -> None:
        """A type that is null or missing is not refused"""
        response = rest_api.get(SINGLE_URL.format(public_id=public_id), **_caller())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == public_id

    def test_the_admin_reads_a_hidden_log(self, rest_api) -> None:
        """Nothing is denied to the admin group"""
        assert rest_api.get(SINGLE_URL.format(public_id=HIDDEN_CHILD_LOG_ID)).status_code == HTTPStatus.OK


class TestDelete:
    """DELETE /object_relation_logs/<id> removes only a log the caller can see"""

    @pytest.mark.parametrize('public_id', HIDDEN_LOG_IDS, ids=['hidden-child', 'hidden-parent'])
    def test_a_hidden_log_is_a_403_and_kept(self, rest_api, logs, public_id: int) -> None:
        """The record of a hidden relation cannot be erased by someone who cannot read it"""
        response = rest_api.delete(SINGLE_URL.format(public_id=public_id), **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE.format(public_id=public_id)
        assert _stored_ids(logs) == set(ALL_LOG_IDS)

    def test_a_readable_log_is_deleted_and_answered(self, rest_api, logs) -> None:
        """The response is the document this request removed"""
        response = rest_api.delete(SINGLE_URL.format(public_id=READABLE_LOG_ID), **_caller())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['raw']['public_id'] == READABLE_LOG_ID
        assert _stored_ids(logs) == set(ALL_LOG_IDS) - {READABLE_LOG_ID}

    def test_a_log_deleted_meanwhile_is_a_404(self, rest_api, logs, monkeypatch: pytest.MonkeyPatch) -> None:
        """The read found it, another request removed it before the delete ran"""
        original = relations_helper.read_object_relation_log_or_abort

        def _read_then_lose(manager: Any, public_id: int, denied: list[int]) -> dict[str, Any]:
            found: dict[str, Any] = original(manager, public_id, denied)
            logs.delete_one({'public_id': public_id})

            return found

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.relation_routes.object_relation_logs_routes.'
            'read_object_relation_log_or_abort', _read_then_lose,
        )

        response = rest_api.delete(SINGLE_URL.format(public_id=READABLE_LOG_ID), **_caller())

        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize('call', [
    lambda api: api.get(LIST_URL, **_caller()),
    lambda api: api.get(SINGLE_URL.format(public_id=READABLE_LOG_ID), **_caller()),
    lambda api: api.delete(SINGLE_URL.format(public_id=READABLE_LOG_ID), **_caller()),
], ids=['list', 'single', 'delete'])
def test_a_failed_type_acl_read_is_a_400_and_deletes_nothing(rest_api, logs, monkeypatch: pytest.MonkeyPatch,
                                                              call: Any) -> None:
    """Never read as "nothing denied" """
    monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', _fail)

    response = call(rest_api)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE
    assert _stored_ids(logs) == set(ALL_LOG_IDS)
