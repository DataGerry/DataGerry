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
Unit tests for the CmdbObjectRelation write checks of relations_helper and object_relation_routes

Pure tests: the objects manager is a stub and the caller's denied types are handed in. Pinned:

  - ``resolve_object_relation_endpoints`` answers the endpoints' REAL type ids, reads both objects in one projected
    query, and refuses a missing, unreadable or wrong-typed endpoint per side - the parent judged by
    ``parent_type_ids``, the child by ``child_type_ids``, as the definition-update cascade judges them
  - an unreadable endpoint gets the same answer as a missing one
  - ``object_relation_field_values_blocker`` holds the values to the relation's declared fields, once each
  - ``stamp_object_relation_references`` overwrites whatever type ids the body sent
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.relation_model import RelationKey
from cmdb.interface.rest_api.routes.relation_routes import object_relation_routes, relations_helper
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    ENDPOINT_PROJECTION,
    guard_object_relation_field_values,
    object_relation_field_values_blocker,
    resolve_object_relation_endpoints,
)
from cmdb.interface.rest_api.routes.relation_routes.object_relation_routes import stamp_object_relation_references
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 5
PARENT_ID: int = 10
CHILD_ID: int = 20
PARENT_TYPE: int = 1
CHILD_TYPE: int = 2
OTHER_TYPE: int = 3
FORGED_TYPE: int = 99
REQUEST_USER = MagicMock(name='request_user')

RELATION: dict[str, Any] = {
    RelationKey.PUBLIC_ID.value: RELATION_ID,
    RelationKey.PARENT_TYPE_IDS.value: [PARENT_TYPE],
    RelationKey.CHILD_TYPE_IDS.value: [CHILD_TYPE],
    RelationKey.FIELDS.value: [{'name': 'cable', 'type': 'text'}, {'name': 'port', 'type': 'text'}],
}


def _objects(stored: dict[int, int]) -> MagicMock:
    """An objects manager whose find answers the given object -> type pairs"""
    manager = MagicMock()
    manager.find.return_value = [{'public_id': object_id, 'type_id': type_id} for object_id, type_id in stored.items()]

    return manager


def _resolve(stored: dict[int, int], parent_id: Any = PARENT_ID, child_id: Any = CHILD_ID,
             denied: list[int] | None = None) -> tuple[int, int]:
    """Runs the resolver against the given stored objects, with nothing denied unless given"""
    return resolve_object_relation_endpoints(RELATION, parent_id, child_id, _objects(stored), denied or [])


class TestResolveObjectRelationEndpoints:
    """Both endpoints read, judged per side, and their real types answered"""

    def test_answers_the_endpoints_real_types(self) -> None:
        """The types the route stores come from the objects"""
        assert _resolve({PARENT_ID: PARENT_TYPE, CHILD_ID: CHILD_TYPE}) == (PARENT_TYPE, CHILD_TYPE)

    def test_the_denied_types_are_not_read_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The route resolves them once and hands them in, so an update reads them once for both of its checks"""
        resolver = MagicMock()
        monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', resolver)

        _resolve({PARENT_ID: PARENT_TYPE, CHILD_ID: CHILD_TYPE})

        resolver.assert_not_called()

    def test_both_objects_are_read_in_one_projected_query(self) -> None:
        """Existence and type, nothing more"""
        manager = _objects({PARENT_ID: PARENT_TYPE, CHILD_ID: CHILD_TYPE})

        resolve_object_relation_endpoints(RELATION, PARENT_ID, CHILD_ID, manager, [])

        manager.find.assert_called_once_with(
            criteria={'public_id': {'$in': [PARENT_ID, CHILD_ID]}}, projection=ENDPOINT_PROJECTION,
        )

    @pytest.mark.parametrize('stored, missing, role', [
        ({CHILD_ID: CHILD_TYPE}, PARENT_ID, 'parent'),
        ({PARENT_ID: PARENT_TYPE}, CHILD_ID, 'child'),
    ])
    def test_a_missing_endpoint_is_refused_and_named(self, stored: dict[int, int],
                                                      missing: int, role: str) -> None:
        """The message names the side and the id"""
        with pytest.raises(HTTPException) as caught:
            _resolve(stored)

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert role in caught.value.description
        assert str(missing) in caught.value.description

    def test_an_unreadable_endpoint_is_answered_like_a_missing_one(self) -> None:
        """Nothing in the answer tells the caller the object exists"""
        with pytest.raises(HTTPException) as unreadable:
            _resolve({PARENT_ID: PARENT_TYPE, CHILD_ID: CHILD_TYPE}, denied=[CHILD_TYPE])
        with pytest.raises(HTTPException) as missing:
            _resolve({PARENT_ID: PARENT_TYPE})

        assert unreadable.value.description == missing.value.description

    @pytest.mark.parametrize('stored, type_id, role', [
        ({PARENT_ID: OTHER_TYPE, CHILD_ID: CHILD_TYPE}, OTHER_TYPE, 'parent'),
        ({PARENT_ID: PARENT_TYPE, CHILD_ID: OTHER_TYPE}, OTHER_TYPE, 'child'),
        ({PARENT_ID: CHILD_TYPE, CHILD_ID: PARENT_TYPE}, CHILD_TYPE, 'parent'),
    ], ids=['parent-not-allowed', 'child-not-allowed', 'sides-swapped'])
    def test_a_type_the_side_does_not_allow_is_refused(self, stored: dict[int, int],
                                                        type_id: int, role: str) -> None:
        """Per side: a parent type is not allowed as a child, and the other way round"""
        with pytest.raises(HTTPException) as caught:
            _resolve(stored)

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert f'Type with ID:{type_id}' in caught.value.description
        assert role in caught.value.description

    @pytest.mark.parametrize('parent_id, child_id', [(None, CHILD_ID), (PARENT_ID, PARENT_ID)])
    def test_the_shape_rules_come_first(self, parent_id: Any, child_id: Any) -> None:
        """A missing id or the same object on both sides is refused before anything is read"""
        manager = _objects({})

        with pytest.raises(HTTPException):
            resolve_object_relation_endpoints(RELATION, parent_id, child_id, manager, [])

        manager.find.assert_not_called()


class TestFieldValues:
    """Every value names a declared field, once"""

    @pytest.mark.parametrize('field_values', [
        None, [], [{'name': 'cable', 'value': 'x'}], [{'name': 'cable', 'value': ''}, {'name': 'port', 'value': 1}],
    ], ids=['absent', 'empty', 'one', 'two'])
    def test_declared_names_pass(self, field_values: Any) -> None:
        """Including no values at all"""
        assert object_relation_field_values_blocker(RELATION, field_values) is None

    def test_an_undeclared_name_is_refused_and_named(self) -> None:
        """The relation's field cascade would never reach it"""
        blocker = object_relation_field_values_blocker(RELATION, [{'name': 'cable'}, {'name': 'colour'}])

        assert 'colour' in blocker
        assert str(RELATION_ID) in blocker

    def test_a_repeated_name_is_refused(self) -> None:
        """Two values for one field: which one is shown would depend on the order"""
        blocker = object_relation_field_values_blocker(RELATION, [{'name': 'cable'}, {'name': 'cable'}])

        assert 'cable' in blocker

    def test_a_relation_without_fields_takes_no_values(self) -> None:
        """Older relations may carry no field list"""
        assert object_relation_field_values_blocker({RelationKey.PUBLIC_ID.value: RELATION_ID}, [{'name': 'cable'}])

    def test_the_guard_answers_400(self) -> None:
        """The route-facing form"""
        with pytest.raises(HTTPException) as caught:
            guard_object_relation_field_values(RELATION, [{'name': 'colour'}])

        assert caught.value.code == HTTPStatus.BAD_REQUEST


def test_the_route_stamps_the_real_types_over_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forged type id in the body never reaches the document"""
    monkeypatch.setattr(object_relation_routes.ManagerProvider, 'get_manager',
                        lambda *_args: _objects({PARENT_ID: PARENT_TYPE, CHILD_ID: CHILD_TYPE}))
    data: dict[str, Any] = {
        'relation_parent_id': PARENT_ID, 'relation_parent_type_id': FORGED_TYPE,
        'relation_child_id': CHILD_ID, 'relation_child_type_id': FORGED_TYPE,
        'field_values': [{'name': 'cable', 'value': 'x'}],
    }

    stamp_object_relation_references(data, RELATION, REQUEST_USER, [])

    assert data['relation_parent_type_id'] == PARENT_TYPE
    assert data['relation_child_type_id'] == CHILD_TYPE
