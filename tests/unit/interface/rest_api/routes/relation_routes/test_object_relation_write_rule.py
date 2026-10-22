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
Unit tests for the object-relation write rule: a stored CmdbObjectRelation is changed and removed under the rule
of the reads

Pure tests: the managers are stubs. Pinned:

  - ``read_object_relation_or_abort`` answers the stored relation, a 404 for a missing one and a 403 for one with
    a denied type at either end; a side with no type stamped is not refused
  - ``abort_if_object_relation_moved`` refuses a payload naming another CmdbRelation, naming both
  - ``build_readable_object_relation_criteria`` is the id alone with nothing denied, else the id plus the readable
    condition on both stamped types
  - ``abort_if_selection_holds_hidden_relation`` reads nothing with nothing denied, else one projected read limited
    to one document, and refuses with a 403 naming the hidden relation it found
  - ``delete_object_relations`` deletes each id under the readable condition
  - ``build_unreadable_endpoints_condition`` matches a denied type on either side
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.object_relations_manager import build_unreadable_endpoints_condition
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_NOT_FOUND_MESSAGE,
    OBJECT_RELATION_RELATION_CHANGED_MESSAGE,
)
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    OBJECT_RELATION_ID_PROJECTION,
    abort_if_object_relation_moved,
    abort_if_selection_holds_hidden_relation,
    build_readable_object_relation_criteria,
    delete_object_relations,
    read_object_relation_or_abort,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_RELATION_ID: int = 71
SECOND_OBJECT_RELATION_ID: int = 72
STORED_RELATION_ID: int = 81
SENT_RELATION_ID: int = 82
PARENT_TYPE_ID: int = 91
CHILD_TYPE_ID: int = 92
DENIED_TYPE_ID: int = 93
OTHER_DENIED_TYPE_ID: int = 94
DENIED: list[int] = [DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID]


def _stored(parent_type_id: int | None = PARENT_TYPE_ID, child_type_id: int | None = CHILD_TYPE_ID) -> dict[str, Any]:
    """A stored object relation with the given stamped types"""
    return {
        'public_id': OBJECT_RELATION_ID, 'relation_id': STORED_RELATION_ID,
        'relation_parent_type_id': parent_type_id, 'relation_child_type_id': child_type_id,
    }


def _reading(document: dict[str, Any] | None) -> MagicMock:
    """An ObjectRelationsManager whose single read answers the given document"""
    manager = MagicMock()
    manager.get_object_relation.return_value = document

    return manager


class TestReadObjectRelationOrAbort:
    """The entry of every route addressing a stored relation"""

    def test_a_readable_relation_is_answered(self) -> None:
        """As stored, read by its id"""
        manager = _reading(_stored())

        assert read_object_relation_or_abort(manager, OBJECT_RELATION_ID, DENIED) == _stored()
        manager.get_object_relation.assert_called_once_with(OBJECT_RELATION_ID)

    def test_a_missing_relation_is_a_404_naming_it(self) -> None:
        """Before any ACL judgement"""
        with pytest.raises(HTTPException) as caught:
            read_object_relation_or_abort(_reading(None), OBJECT_RELATION_ID, DENIED)

        assert caught.value.code == HTTPStatus.NOT_FOUND
        assert caught.value.description == OBJECT_RELATION_NOT_FOUND_MESSAGE.format(public_id=OBJECT_RELATION_ID)

    @pytest.mark.parametrize('parent_type_id, child_type_id', [
        (DENIED_TYPE_ID, CHILD_TYPE_ID), (PARENT_TYPE_ID, OTHER_DENIED_TYPE_ID), (DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID),
    ], ids=['parent-denied', 'child-denied', 'both-denied'])
    def test_a_denied_type_at_either_end_is_a_403_naming_it(self, parent_type_id: int, child_type_id: int) -> None:
        """The less readable of the two objects decides"""
        with pytest.raises(HTTPException) as caught:
            read_object_relation_or_abort(_reading(_stored(parent_type_id, child_type_id)), OBJECT_RELATION_ID, DENIED)

        assert caught.value.code == HTTPStatus.FORBIDDEN
        assert caught.value.description == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=OBJECT_RELATION_ID)

    def test_a_side_without_a_stamped_type_is_not_refused(self) -> None:
        """The rule of the reads"""
        document: dict[str, Any] = _stored(None, None)

        assert read_object_relation_or_abort(_reading(document), OBJECT_RELATION_ID, DENIED) == document

    def test_with_nothing_denied_every_relation_is_answered(self) -> None:
        """The admin's case"""
        document: dict[str, Any] = _stored(DENIED_TYPE_ID, OTHER_DENIED_TYPE_ID)

        assert read_object_relation_or_abort(_reading(document), OBJECT_RELATION_ID, []) == document


class TestAbortIfObjectRelationMoved:
    """An instance stays with its CmdbRelation"""

    def test_the_same_relation_passes(self) -> None:
        """The frontend's case: it sends the relation it edits"""
        abort_if_object_relation_moved(_stored(), {'relation_id': STORED_RELATION_ID})

    def test_another_relation_is_a_400_naming_both(self) -> None:
        """The instance, the relation it belongs to and the one the body named"""
        with pytest.raises(HTTPException) as caught:
            abort_if_object_relation_moved(_stored(), {'relation_id': SENT_RELATION_ID})

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert caught.value.description == OBJECT_RELATION_RELATION_CHANGED_MESSAGE.format(
            public_id=OBJECT_RELATION_ID, stored_relation_id=STORED_RELATION_ID, sent_relation_id=SENT_RELATION_ID,
        )


class TestBuildReadableObjectRelationCriteria:
    """The filter a delete runs with"""

    def test_with_nothing_denied_it_is_the_id_alone(self) -> None:
        """No condition to add"""
        assert build_readable_object_relation_criteria(OBJECT_RELATION_ID, []) == {'public_id': OBJECT_RELATION_ID}

    def test_with_denied_types_both_ends_are_held_to_them(self) -> None:
        """The id plus the readable condition"""
        assert build_readable_object_relation_criteria(OBJECT_RELATION_ID, DENIED) == {
            'public_id': OBJECT_RELATION_ID,
            'relation_parent_type_id': {'$nin': DENIED},
            'relation_child_type_id': {'$nin': DENIED},
        }


def _finding(found: list[dict[str, Any]]) -> MagicMock:
    """An ObjectRelationsManager whose find answers the given documents"""
    manager = MagicMock()
    manager.find.return_value = found

    return manager


class TestAbortIfSelectionHoldsHiddenRelation:
    """A bulk selection is judged whole, before anything is deleted"""

    def test_with_nothing_denied_nothing_is_read(self) -> None:
        """No relation can be hidden"""
        manager = _finding([])

        abort_if_selection_holds_hidden_relation(manager, [OBJECT_RELATION_ID], [])

        manager.find.assert_not_called()

    def test_one_projected_read_stops_at_the_first_hidden_relation(self) -> None:
        """The selection, restricted to the unreadable condition, one id-only document"""
        manager = _finding([])

        abort_if_selection_holds_hidden_relation(manager, [OBJECT_RELATION_ID, SECOND_OBJECT_RELATION_ID], DENIED)

        manager.find.assert_called_once_with(
            criteria={'$and': [
                {'public_id': {'$in': [OBJECT_RELATION_ID, SECOND_OBJECT_RELATION_ID]}},
                build_unreadable_endpoints_condition(DENIED),
            ]},
            projection=OBJECT_RELATION_ID_PROJECTION,
            limit=1,
        )

    def test_a_hidden_relation_is_a_403_naming_it(self) -> None:
        """The one the read found"""
        manager = _finding([{'public_id': SECOND_OBJECT_RELATION_ID}])

        with pytest.raises(HTTPException) as caught:
            abort_if_selection_holds_hidden_relation(manager, [OBJECT_RELATION_ID, SECOND_OBJECT_RELATION_ID], DENIED)

        assert caught.value.code == HTTPStatus.FORBIDDEN
        assert caught.value.description == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(
            public_id=SECOND_OBJECT_RELATION_ID,
        )

    def test_a_selection_without_a_hidden_relation_passes(self) -> None:
        """Nothing found"""
        abort_if_selection_holds_hidden_relation(_finding([]), [OBJECT_RELATION_ID], DENIED)


def test_each_bulk_delete_runs_under_the_readable_condition() -> None:
    """A relation re-pointed to a hidden object since the selection was judged is not matched"""
    manager = MagicMock()
    manager.find_one_and_delete.return_value = None

    delete_object_relations(manager, [OBJECT_RELATION_ID, SECOND_OBJECT_RELATION_ID], [], DENIED)

    assert [call.args[0] for call in manager.find_one_and_delete.call_args_list] == [
        build_readable_object_relation_criteria(OBJECT_RELATION_ID, DENIED),
        build_readable_object_relation_criteria(SECOND_OBJECT_RELATION_ID, DENIED),
    ]


def test_the_unreadable_condition_matches_a_denied_type_on_either_side() -> None:
    """The complement of the readable condition"""
    assert build_unreadable_endpoints_condition(DENIED) == {'$or': [
        {'relation_parent_type_id': {'$in': DENIED}},
        {'relation_child_type_id': {'$in': DENIED}},
    ]}
