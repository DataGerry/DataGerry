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
Functional tests for the object-relation write rule: a stored CmdbObjectRelation can be updated and deleted exactly
when it can be read - when the caller may read the objects at both of its ends

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type, a PLAIN one, and a HIDDEN one only the admin group
may read) and four relations: VISIBLE->PLAIN (readable), VISIBLE->HIDDEN, HIDDEN->VISIBLE and HIDDEN->PLAIN. The
seed's editor group is the caller, given the edit and delete rights. Pinned, for that caller:

  - an update of a hidden relation is a 403 naming it and changes nothing - also when its body is unusable, since
    the stored relation is judged first; a missing one is a 404 whatever the body
  - an update naming another CmdbRelation is a 400 and changes nothing
  - the update resolves the caller's denied types once, for the stored relation and the new endpoints together
  - a delete of a hidden relation is a 403, deletes nothing and logs nothing; the history entry of a delete is the
    document the delete removed, and a relation re-pointed to a hidden object before the delete ran is a 404
  - a bulk delete whose selection holds a hidden relation is a 403 naming it, before anything is deleted; with
    nothing denied the selection is not read at all; a failed selection read is a 400
  - a failed type-ACL read is a 400 on all three routes
  - the admin, who may read every type, updates and deletes every relation as before
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.interface.rest_api.routes.relation_routes import relations_helper
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_BULK_SELECTION_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_NOT_FOUND_MESSAGE,
    OBJECT_RELATION_RELATION_CHANGED_MESSAGE,
    ObjectRelationRight,
)
from cmdb.errors.manager import BaseManagerGetError
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

SINGLE_URL: str = '/object_relations/{public_id}'
BULK_URL: str = '/object_relations/delete/many'

RELATION_ID: int = 89751
OTHER_RELATION_ID: int = 89752
READABLE_ID: int = 89761          # VISIBLE -> PLAIN
HIDDEN_CHILD_ID: int = 89762      # VISIBLE -> HIDDEN
HIDDEN_PARENT_ID: int = 89763     # HIDDEN -> VISIBLE
HIDDEN_ONLY_ID: int = 89764       # HIDDEN -> PLAIN
MISSING_ID: int = 89769
ALL_RELATION_IDS: list[int] = [READABLE_ID, HIDDEN_CHILD_ID, HIDDEN_PARENT_ID, HIDDEN_ONLY_ID]
HIDDEN_RELATION_IDS: list[int] = [HIDDEN_CHILD_ID, HIDDEN_PARENT_ID, HIDDEN_ONLY_ID]

FIELD_NAME: str = 'port'
STORED_VALUE: str = 'stored-value'
UPDATED_VALUE: str = 'updated-value'
DELETE_ACTION: str = 'DELETE'
WRITE_RIGHTS: list[str] = [ObjectRelationRight.EDIT.value, ObjectRelationRight.DELETE.value]

VISIBLE: tuple[int, int] = (seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID)
HIDDEN: tuple[int, int] = (seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID)
PLAIN: tuple[int, int] = (seed.PLAIN_ID, seed.PLAIN_TYPE_ID)
ENDS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    READABLE_ID: (VISIBLE, PLAIN),
    HIDDEN_CHILD_ID: (VISIBLE, HIDDEN),
    HIDDEN_PARENT_ID: (HIDDEN, VISIBLE),
    HIDDEN_ONLY_ID: (HIDDEN, PLAIN),
}


def _relation(public_id: int) -> dict[str, Any]:
    """The stored object relation of the given id, between its two seeded ends"""
    parent, child = ENDS[public_id]

    return {
        'public_id': public_id, 'relation_id': RELATION_ID, 'author_id': seed.EDITOR_ID,
        'relation_parent_id': parent[0], 'relation_parent_type_id': parent[1],
        'relation_child_id': child[0], 'relation_child_type_id': child[1],
        'field_values': [{'name': FIELD_NAME, 'value': STORED_VALUE}],
    }


def _body(public_id: int, **overrides: Any) -> dict[str, Any]:
    """A PUT body replacing the relation with itself, its field value changed"""
    body: dict[str, Any] = _relation(public_id)
    body['field_values'] = [{'name': FIELD_NAME, 'value': UPDATED_VALUE}]

    return {**body, **overrides}


@pytest.fixture(name='relations', autouse=True)
def fixture_relations(database_manager: MongoDatabaseManager, database_name: str):
    """The ACL seed, its editor given the write rights, the relation definition and the four relations"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': {'$each': WRITE_RIGHTS}}},
    )
    definitions = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)

    def _purge() -> None:
        definitions.delete_many({'public_id': {'$in': [RELATION_ID, OTHER_RELATION_ID]}})
        object_relations.delete_many({'public_id': {'$in': ALL_RELATION_IDS}})
        logs.delete_many({'object_relation_id': {'$in': ALL_RELATION_IDS}})

    _purge()
    all_type_ids: list[int] = [seed.VISIBLE_TYPE_ID, seed.HIDDEN_TYPE_ID, seed.PLAIN_TYPE_ID]
    definitions.insert_many([{
        'public_id': definition_id, 'relation_name': f'write-acl-relation-{definition_id}',
        'relation_name_parent': 'Hosts', 'relation_name_child': 'Hosted On',
        'relation_icon_parent': 'fas fa-server', 'relation_icon_child': 'fas fa-network-wired',
        'relation_color_parent': '#111111', 'relation_color_child': '#222222',
        'parent_type_ids': all_type_ids, 'child_type_ids': all_type_ids,
        'fields': [{'name': FIELD_NAME, 'type': 'text', 'label': 'Port'}], 'sections': [],
    } for definition_id in (RELATION_ID, OTHER_RELATION_ID)])
    object_relations.insert_many([_relation(public_id) for public_id in ALL_RELATION_IDS])
    yield object_relations
    _purge()
    seed.purge(database_manager, database_name)


def _caller() -> dict[str, Any]:
    """The request kwargs that send the seed's editor"""
    return {'user': seed.location_editor()}


def _stored_value(relations: Any, public_id: int) -> str:
    """The stored field value of one relation"""
    return relations.find_one({'public_id': public_id})['field_values'][0]['value']


def _stored_ids(relations: Any) -> set[int]:
    """The seeded relations still stored"""
    return {document['public_id'] for document in relations.find({'public_id': {'$in': ALL_RELATION_IDS}})}


def _logs(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[dict[str, Any]]:
    """The history entries of one relation, oldest first"""
    return list(database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)
                .find({'object_relation_id': public_id}).sort('public_id', 1))


def _fail(*_args: Any, **_kwargs: Any) -> None:
    """Stands in for a read that fails"""
    raise BaseManagerGetError('read failed')


class TestUpdate:
    """PUT /object_relations/<id> replaces only a relation the caller can see"""

    def test_a_readable_relation_is_updated(self, rest_api, relations) -> None:
        """The rule does not get in the way of an allowed write"""
        response = rest_api.put(SINGLE_URL.format(public_id=READABLE_ID), json=_body(READABLE_ID), **_caller())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(relations, READABLE_ID) == UPDATED_VALUE

    @pytest.mark.parametrize('public_id', HIDDEN_RELATION_IDS, ids=['hidden-child', 'hidden-parent', 'hidden-both'])
    def test_a_hidden_relation_is_a_403_and_unchanged(self, rest_api, relations, public_id: int) -> None:
        """Hidden at either end is enough"""
        response = rest_api.put(SINGLE_URL.format(public_id=public_id), json=_body(public_id), **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=public_id)
        assert _stored_value(relations, public_id) == STORED_VALUE

    def test_re_pointing_a_hidden_relation_to_readable_objects_is_refused(self, rest_api, relations) -> None:
        """The way a hidden relation would have been taken out of everyone else's view"""
        body: dict[str, Any] = _body(
            HIDDEN_CHILD_ID, relation_child_id=seed.PLAIN_ID, relation_child_type_id=seed.PLAIN_TYPE_ID,
        )

        response = rest_api.put(SINGLE_URL.format(public_id=HIDDEN_CHILD_ID), json=body, **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert relations.find_one({'public_id': HIDDEN_CHILD_ID})['relation_child_id'] == seed.HIDDEN_ID

    def test_the_stored_relation_is_judged_before_the_body(self, rest_api) -> None:
        """A body whose endpoint does not exist would be a 400 - the hidden relation answers first"""
        body: dict[str, Any] = _body(HIDDEN_ONLY_ID, relation_child_id=seed.MISSING_OBJECT_ID)

        response = rest_api.put(SINGLE_URL.format(public_id=HIDDEN_ONLY_ID), json=body, **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_a_missing_relation_is_a_404_whatever_the_body(self, rest_api) -> None:
        """Before, a body with a missing endpoint answered 400 for an id that does not exist"""
        body: dict[str, Any] = _body(READABLE_ID, relation_child_id=seed.MISSING_OBJECT_ID)

        response = rest_api.put(SINGLE_URL.format(public_id=MISSING_ID), json=body, **_caller())

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == OBJECT_RELATION_NOT_FOUND_MESSAGE.format(public_id=MISSING_ID)

    def test_naming_another_relation_is_a_400_and_unchanged(self, rest_api, relations) -> None:
        """An instance stays with its definition"""
        body: dict[str, Any] = _body(READABLE_ID, relation_id=OTHER_RELATION_ID)

        response = rest_api.put(SINGLE_URL.format(public_id=READABLE_ID), json=body, **_caller())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_RELATION_CHANGED_MESSAGE.format(
            public_id=READABLE_ID, stored_relation_id=RELATION_ID, sent_relation_id=OTHER_RELATION_ID,
        )
        stored: dict[str, Any] = relations.find_one({'public_id': READABLE_ID})
        assert stored['relation_id'] == RELATION_ID
        assert stored['field_values'][0]['value'] == STORED_VALUE

    def test_the_denied_types_are_resolved_once(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """One read for the stored relation and the new endpoints together"""
        original = relations_helper.resolve_denied_type_ids
        calls: list[Any] = []

        def _counting(*args: Any) -> list[int]:
            calls.append(args)

            return original(*args)

        monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', _counting)

        response = rest_api.put(SINGLE_URL.format(public_id=READABLE_ID), json=_body(READABLE_ID), **_caller())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert len(calls) == 1

    def test_the_admin_updates_a_relation_the_caller_may_not_see(self, rest_api, relations) -> None:
        """The admin group may read the hidden type"""
        response = rest_api.put(SINGLE_URL.format(public_id=HIDDEN_ONLY_ID), json=_body(HIDDEN_ONLY_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(relations, HIDDEN_ONLY_ID) == UPDATED_VALUE


class TestSingleDelete:
    """DELETE /object_relations/<id> removes only a relation the caller can see"""

    def test_a_readable_relation_is_deleted_and_logged(self, rest_api, relations, database_manager,
                                                         database_name: str) -> None:
        """One history entry"""
        response = rest_api.delete(SINGLE_URL.format(public_id=READABLE_ID), **_caller())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert READABLE_ID not in _stored_ids(relations)
        assert [log['action'] for log in _logs(database_manager, database_name, READABLE_ID)] == [DELETE_ACTION]

    @pytest.mark.parametrize('public_id', HIDDEN_RELATION_IDS, ids=['hidden-child', 'hidden-parent', 'hidden-both'])
    def test_a_hidden_relation_is_a_403_kept_and_not_logged(self, rest_api, relations, database_manager,
                                                              database_name: str, public_id: int) -> None:
        """Nothing deleted, nothing recorded"""
        response = rest_api.delete(SINGLE_URL.format(public_id=public_id), **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=public_id)
        assert public_id in _stored_ids(relations)
        assert not _logs(database_manager, database_name, public_id)

    def test_a_missing_relation_is_a_404(self, rest_api) -> None:
        """Named"""
        response = rest_api.delete(SINGLE_URL.format(public_id=MISSING_ID), **_caller())

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == OBJECT_RELATION_NOT_FOUND_MESSAGE.format(public_id=MISSING_ID)

    def test_the_history_records_the_document_the_delete_removed(
        self, rest_api, relations, monkeypatch: pytest.MonkeyPatch, database_manager, database_name: str,
    ) -> None:
        """Another request re-points the child between this one's read and its delete"""
        original = BaseManager.find_one_and_delete

        def _edited_first(manager: BaseManager, criteria: dict[str, Any]) -> dict[str, Any] | None:
            relations.update_one({'public_id': criteria['public_id']}, {'$set': {
                'relation_child_id': seed.VISIBLE_ID, 'relation_child_type_id': seed.VISIBLE_TYPE_ID,
            }})

            return original(manager, criteria)

        monkeypatch.setattr(BaseManager, 'find_one_and_delete', _edited_first)

        response = rest_api.delete(SINGLE_URL.format(public_id=READABLE_ID), **_caller())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['raw']['relation_child_id'] == seed.VISIBLE_ID
        assert [log['object_relation_child_id']
                for log in _logs(database_manager, database_name, READABLE_ID)] == [seed.VISIBLE_ID]

    def test_a_relation_re_pointed_to_a_hidden_object_meanwhile_is_kept(
        self, rest_api, relations, monkeypatch: pytest.MonkeyPatch, database_manager, database_name: str,
    ) -> None:
        """The delete itself still requires both objects to be readable"""
        original = BaseManager.find_one_and_delete

        def _hidden_first(manager: BaseManager, criteria: dict[str, Any]) -> dict[str, Any] | None:
            relations.update_one({'public_id': criteria['public_id']}, {'$set': {
                'relation_child_id': seed.HIDDEN_ID, 'relation_child_type_id': seed.HIDDEN_TYPE_ID,
            }})

            return original(manager, criteria)

        monkeypatch.setattr(BaseManager, 'find_one_and_delete', _hidden_first)

        response = rest_api.delete(SINGLE_URL.format(public_id=READABLE_ID), **_caller())

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert READABLE_ID in _stored_ids(relations)
        assert not _logs(database_manager, database_name, READABLE_ID)

    def test_the_admin_deletes_a_relation_the_caller_may_not_see(self, rest_api, relations) -> None:
        """The admin group may read the hidden type"""
        response = rest_api.delete(SINGLE_URL.format(public_id=HIDDEN_ONLY_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert HIDDEN_ONLY_ID not in _stored_ids(relations)


class TestBulkDelete:
    """POST /object_relations/delete/many refuses a selection holding a hidden relation, whole"""

    def test_a_readable_selection_is_deleted(self, rest_api, relations) -> None:
        """The rule does not get in the way of an allowed delete"""
        response = rest_api.post(BULK_URL, json={'target_ids': [READABLE_ID, MISSING_ID]}, **_caller())

        assert response.status_code == HTTPStatus.OK
        assert READABLE_ID not in _stored_ids(relations)

    @pytest.mark.parametrize('hidden_id', HIDDEN_RELATION_IDS, ids=['hidden-child', 'hidden-parent', 'hidden-both'])
    def test_one_hidden_relation_refuses_the_selection(self, rest_api, relations, database_manager,
                                                       database_name: str, hidden_id: int) -> None:
        """403 naming it; the readable one is not deleted either, and nothing is logged"""
        response = rest_api.post(BULK_URL, json={'target_ids': [READABLE_ID, hidden_id]}, **_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=hidden_id)
        assert _stored_ids(relations) == set(ALL_RELATION_IDS)
        assert not _logs(database_manager, database_name, READABLE_ID)

    def test_a_failed_selection_read_is_a_400(self, rest_api, relations, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing is deleted"""
        monkeypatch.setattr(ObjectRelationsManager, 'find', _fail)

        response = rest_api.post(BULK_URL, json={'target_ids': [READABLE_ID]}, **_caller())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_BULK_SELECTION_LOOKUP_FAILED_MESSAGE
        assert _stored_ids(relations) == set(ALL_RELATION_IDS)

    def test_with_nothing_denied_the_selection_is_not_read(self, rest_api, relations,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
        """The admin may read every type: a failing selection read is never reached"""
        monkeypatch.setattr(ObjectRelationsManager, 'find', _fail)

        response = rest_api.post(BULK_URL, json={'target_ids': HIDDEN_RELATION_IDS})

        assert response.status_code == HTTPStatus.OK
        assert _stored_ids(relations) == {READABLE_ID}


@pytest.mark.parametrize('call', [
    lambda api: api.put(SINGLE_URL.format(public_id=READABLE_ID), json=_body(READABLE_ID), **_caller()),
    lambda api: api.delete(SINGLE_URL.format(public_id=READABLE_ID), **_caller()),
    lambda api: api.post(BULK_URL, json={'target_ids': [READABLE_ID]}, **_caller()),
], ids=['update', 'delete', 'bulk-delete'])
def test_a_failed_type_acl_read_is_a_400_and_changes_nothing(rest_api, relations, monkeypatch: pytest.MonkeyPatch,
                                                              call: Any) -> None:
    """Never read as "nothing denied" """
    monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', _fail)

    response = call(rest_api)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE
    assert _stored_value(relations, READABLE_ID) == STORED_VALUE
