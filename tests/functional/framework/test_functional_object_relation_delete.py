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
Functional tests for deleting CmdbObjectRelations: what a request deletes is what it records

``POST /object_relations/delete/many`` and ``DELETE /object_relations/<id>``. Pinned:

  - the bulk body is an object carrying a LIST of ids: a string selection is refused instead of being read digit by
    digit, a number or a list body is a 400 rather than a 500, and more than MAX_BULK_DELETE_OBJECT_RELATIONS
    distinct ids are refused
  - a relation another writer deletes while the request runs is neither counted nor logged by it - on the bulk and on
    the single route (which then answers 404)
  - an id named twice is deleted and logged once
  - a delete that fails part-way answers 400 naming how many were deleted, and those are logged
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.interface.rest_api.routes.routes_helper import PUBLIC_ID_LIST_NOT_A_LIST_MSG
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    MAX_BULK_DELETE_OBJECT_RELATIONS,
    OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE,
    OBJECT_RELATION_BULK_DELETE_FAILED_MESSAGE,
    OBJECT_RELATION_BULK_NONE_EXIST_MESSAGE,
    OBJECT_RELATION_BULK_TOO_MANY_MESSAGE,
    BulkDeleteKey,
)
from cmdb.errors.manager import BaseManagerDeleteError

from tests.functional.framework.test_functional_object_relation_route import (
    _insert_object_relation_doc,
    _object_relation_logs,
    _purge_object_relation,
)
# -------------------------------------------------------------------------------------------------------------------- #

BULK_URL: str = '/object_relations/delete/many'
SINGLE_URL: str = '/object_relations/{public_id}'

FIRST_ID: int = 78601
SECOND_ID: int = 78602
THIRD_ID: int = 78603
ALL_IDS: list[int] = [FIRST_ID, SECOND_ID, THIRD_ID]

# The digits a string selection would have been read as: two relations nobody named
DIGIT_IDS: list[int] = [1, 2]
DIGIT_STRING: str = '12'

DELETE_ACTION: str = 'DELETE'
TARGET_IDS: str = BulkDeleteKey.TARGET_IDS.value


@pytest.fixture(name='relations')
def fixture_relations(database_manager: MongoDatabaseManager, database_name: str):
    """Three stored CmdbObjectRelations without history, removed again with their logs afterwards"""
    for public_id in ALL_IDS:
        _insert_object_relation_doc(database_manager, database_name, public_id)

    yield database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    for public_id in ALL_IDS:
        _purge_object_relation(database_manager, database_name, public_id)


@pytest.fixture(name='digit_relations')
def fixture_digit_relations(database_manager: MongoDatabaseManager, database_name: str):
    """The relations with public_id 1 and 2, the ids a string selection '12' would have addressed"""
    collection = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    preexisting: set[int] = {doc['public_id'] for doc in collection.find({'public_id': {'$in': DIGIT_IDS}})}

    for public_id in DIGIT_IDS:
        if public_id not in preexisting:
            _insert_object_relation_doc(database_manager, database_name, public_id)

    yield collection

    for public_id in DIGIT_IDS:
        if public_id not in preexisting:
            _purge_object_relation(database_manager, database_name, public_id)


def _stored_ids(collection: Any, public_ids: list[int]) -> list[int]:
    """Which of the given CmdbObjectRelations are still stored"""
    return sorted(doc['public_id'] for doc in collection.find({'public_id': {'$in': public_ids}}))


class TestTheBody:
    """The selection is an object carrying a list of ids"""

    def test_a_string_selection_is_refused_and_deletes_nothing(self, rest_api, digit_relations) -> None:
        """'12' was read as the ids 1 and 2 and deleted both"""
        response = rest_api.post(BULK_URL, json={TARGET_IDS: DIGIT_STRING})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PUBLIC_ID_LIST_NOT_A_LIST_MSG.format(kind='str')
        assert _stored_ids(digit_relations, DIGIT_IDS) == DIGIT_IDS

    @pytest.mark.parametrize('target_ids, kind', [(5, 'int'), ({'7': 1}, 'dict')], ids=['number', 'object'])
    def test_a_selection_that_is_no_list_is_a_400(self, rest_api, target_ids: Any, kind: str) -> None:
        """It was a 500 (a number) or read as its keys (an object)"""
        response = rest_api.post(BULK_URL, json={TARGET_IDS: target_ids})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PUBLIC_ID_LIST_NOT_A_LIST_MSG.format(kind=kind)

    @pytest.mark.parametrize('body', [[FIRST_ID], DIGIT_STRING, 7], ids=['list', 'string', 'number'])
    def test_a_body_that_is_no_object_is_a_400(self, rest_api, relations, body: Any) -> None:
        """It was a 500, and nothing is deleted"""
        response = rest_api.post(BULK_URL, json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE.format(
            key=TARGET_IDS,
        )
        assert _stored_ids(relations, ALL_IDS) == ALL_IDS

    def test_more_than_the_limit_is_refused(self, rest_api, relations) -> None:
        """Distinct ids are counted; nothing is deleted"""
        too_many: list[int] = ALL_IDS + list(range(1, MAX_BULK_DELETE_OBJECT_RELATIONS + 1))

        response = rest_api.post(BULK_URL, json={TARGET_IDS: too_many})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_BULK_TOO_MANY_MESSAGE.format(
            limit=MAX_BULK_DELETE_OBJECT_RELATIONS, count=len(set(too_many)),
        )
        assert _stored_ids(relations, ALL_IDS) == ALL_IDS

    def test_the_limit_counts_distinct_ids(self, rest_api, relations) -> None:
        """One id repeated past the limit is one id"""
        response = rest_api.post(BULK_URL, json={TARGET_IDS: [FIRST_ID] * (MAX_BULK_DELETE_OBJECT_RELATIONS + 1)})

        assert response.status_code == HTTPStatus.OK
        assert _stored_ids(relations, ALL_IDS) == [SECOND_ID, THIRD_ID]


class TestBulkDelete:
    """One DELETE log per relation THIS request deleted"""

    def test_an_id_named_twice_is_deleted_and_logged_once(
        self, rest_api, relations, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Duplicates collapse in the order given"""
        response = rest_api.post(BULK_URL, json={TARGET_IDS: [FIRST_ID, FIRST_ID, str(FIRST_ID)]})

        assert response.status_code == HTTPStatus.OK
        assert _stored_ids(relations, ALL_IDS) == [SECOND_ID, THIRD_ID]
        assert _object_relation_logs(database_manager, database_name, FIRST_ID) == [DELETE_ACTION]

    def test_a_relation_deleted_concurrently_is_not_logged(
        self, rest_api, relations, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Another writer removes the second relation just before this request reaches it"""
        original = BaseManager.find_one_and_delete

        def _racing(manager: BaseManager, criteria: dict[str, Any]) -> dict[str, Any] | None:
            if criteria == {'public_id': SECOND_ID}:
                relations.delete_one({'public_id': SECOND_ID})

            return original(manager, criteria)

        monkeypatch.setattr(BaseManager, 'find_one_and_delete', _racing)

        response = rest_api.post(BULK_URL, json={TARGET_IDS: [FIRST_ID, SECOND_ID]})

        assert response.status_code == HTTPStatus.OK
        assert _object_relation_logs(database_manager, database_name, FIRST_ID) == [DELETE_ACTION]
        assert _object_relation_logs(database_manager, database_name, SECOND_ID) == []

    def test_a_selection_of_which_nothing_was_deleted_is_a_400(self, rest_api, relations, monkeypatch) -> None:
        """Every id was deleted by someone else first: nothing to report as done"""
        original = BaseManager.find_one_and_delete

        def _beaten(manager: BaseManager, criteria: dict[str, Any]) -> dict[str, Any] | None:
            relations.delete_one(criteria)

            return original(manager, criteria)

        monkeypatch.setattr(BaseManager, 'find_one_and_delete', _beaten)

        response = rest_api.post(BULK_URL, json={TARGET_IDS: [FIRST_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_BULK_NONE_EXIST_MESSAGE

    def test_a_failure_part_way_is_a_400_and_logs_what_was_deleted(
        self, rest_api, relations, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The first two are gone and recorded, the third fails and stays"""
        original = BaseManager.find_one_and_delete

        def _failing_third(manager: BaseManager, criteria: dict[str, Any]) -> dict[str, Any] | None:
            if criteria == {'public_id': THIRD_ID}:
                raise BaseManagerDeleteError('boom')

            return original(manager, criteria)

        monkeypatch.setattr(BaseManager, 'find_one_and_delete', _failing_third)

        response = rest_api.post(BULK_URL, json={TARGET_IDS: ALL_IDS})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_BULK_DELETE_FAILED_MESSAGE.format(deleted=2)
        assert _stored_ids(relations, ALL_IDS) == [THIRD_ID]
        assert _object_relation_logs(database_manager, database_name, FIRST_ID) == [DELETE_ACTION]
        assert _object_relation_logs(database_manager, database_name, SECOND_ID) == [DELETE_ACTION]
        assert _object_relation_logs(database_manager, database_name, THIRD_ID) == []


class TestSingleDelete:
    """DELETE /object_relations/<id> records only a deletion it performed"""

    def test_a_relation_deleted_concurrently_is_a_404_without_a_log(
        self, rest_api, relations, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Read by this request, deleted by another before this one's delete ran"""
        original = ObjectRelationsManager.delete_object_relation

        def _beaten(manager: ObjectRelationsManager, public_id: int) -> bool:
            relations.delete_one({'public_id': public_id})

            return original(manager, public_id)

        monkeypatch.setattr(ObjectRelationsManager, 'delete_object_relation', _beaten)

        response = rest_api.delete(SINGLE_URL.format(public_id=FIRST_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert _object_relation_logs(database_manager, database_name, FIRST_ID) == []

    def test_a_delete_is_logged_once(
        self, rest_api, relations, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The ordinary case still records its deletion"""
        response = rest_api.delete(SINGLE_URL.format(public_id=FIRST_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_ids(relations, ALL_IDS) == [SECOND_ID, THIRD_ID]
        assert _object_relation_logs(database_manager, database_name, FIRST_ID) == [DELETE_ACTION]
