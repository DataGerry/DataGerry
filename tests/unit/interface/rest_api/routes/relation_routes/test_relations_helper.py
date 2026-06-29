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
Unit tests for the CmdbRelation route helpers

Pure tests: the ObjectRelationsManager is a MagicMock, so only the comparison logic and the
delete-cascade dispatch are exercised.
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    get_deleted_type_ids,
    handle_deleted_type_ids,
    get_existing_relation_or_abort,
    validate_object_relation_endpoints,
)
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_PUBLIC_ID: int = 5

PARENT_TYPE_A: int = 1
PARENT_TYPE_B: int = 2
CHILD_TYPE_A: int = 3
CHILD_TYPE_B: int = 4


def _relation(public_id: int, parent_ids: list[int], child_ids: list[int]) -> dict[str, Any]:
    """Builds the minimal relation dict the helper reads."""
    return {'public_id': public_id, 'parent_type_ids': parent_ids, 'child_type_ids': child_ids}


# ----------------------------------------------------- get_deleted_type_ids ----------------------------------------- #

class TestGetDeletedTypeIds:
    """Tests for get_deleted_type_ids (pure set difference)."""

    def test_returns_ids_only_in_old(self) -> None:
        """IDs present in old but not in new are returned."""
        assert set(get_deleted_type_ids([1, 2, 3], [2, 3])) == {1}

    def test_returns_empty_when_nothing_removed(self) -> None:
        """No removed ids yields an empty list."""
        assert get_deleted_type_ids([1, 2], [1, 2, 3]) == []


# --------------------------------------------------- handle_deleted_type_ids ---------------------------------------- #

class TestHandleDeletedTypeIds:
    """Tests for handle_deleted_type_ids (cascade dispatch to ObjectRelationsManager)."""

    def test_deletes_object_relations_for_removed_parent_and_child(self) -> None:
        """Removing a parent and a child type triggers one cascade call each (parent flag True/False)."""
        manager = MagicMock()
        old_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A, PARENT_TYPE_B], [CHILD_TYPE_A, CHILD_TYPE_B])
        new_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])

        handle_deleted_type_ids(old_relation, new_relation, manager)

        assert manager.delete_invalidated_object_relations.call_count == 2
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [PARENT_TYPE_B], True)
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [CHILD_TYPE_B], False)

    def test_no_cascade_when_nothing_removed(self) -> None:
        """When no parent/child types are removed, no cascade call is made."""
        manager = MagicMock()
        relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])

        handle_deleted_type_ids(relation, dict(relation), manager)

        manager.delete_invalidated_object_relations.assert_not_called()


# ------------------------------------------------ get_existing_relation_or_abort ------------------------------------ #

class TestGetExistingRelationOrAbort:
    """get_existing_relation_or_abort returns the relation or aborts 400."""

    def test_returns_relation_when_present(self) -> None:
        """An existing relation is returned unchanged."""
        relations_manager = MagicMock()
        relation = {'public_id': RELATION_PUBLIC_ID}
        relations_manager.get_relation.return_value = relation

        assert get_existing_relation_or_abort(relations_manager, RELATION_PUBLIC_ID) is relation
        relations_manager.get_relation.assert_called_once_with(RELATION_PUBLIC_ID)

    def test_aborts_400_when_missing(self) -> None:
        """A missing relation aborts with 400."""
        relations_manager = MagicMock()
        relations_manager.get_relation.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_existing_relation_or_abort(relations_manager, RELATION_PUBLIC_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# --------------------------------------------- validate_object_relation_endpoints ---------------------------------- #

class TestValidateObjectRelationEndpoints:
    """validate_object_relation_endpoints guards distinct, present parent/child objects."""

    def test_passes_for_distinct_endpoints(self) -> None:
        """Distinct, present parent and child ids do not abort."""
        validate_object_relation_endpoints(1, 2)

    @pytest.mark.parametrize('parent_id, child_id', [(None, 2), (1, None), (None, None), (0, 2)])
    def test_aborts_400_when_endpoint_missing(self, parent_id: int | None, child_id: int | None) -> None:
        """A missing parent or child id aborts with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_relation_endpoints(parent_id, child_id)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_aborts_400_when_parent_equals_child(self) -> None:
        """The same object as parent and child aborts with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_relation_endpoints(7, 7)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
