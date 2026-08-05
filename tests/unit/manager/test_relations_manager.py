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
Unit tests for cmdb.manager.relations_manager.RelationsManager

Pure tests: no Mongo. RelationsManager is now a GenericManager subclass, so the CRUD methods are
thin forwarders to the generic item-level CRUD (insert_item / get_item / iterate_items /
update_item / delete_item) - those primitives and their error wrapping are covered by the
GenericManager suite. Here each method is invoked unbound against a ``MagicMock(spec=RelationsManager)``
and asserted to delegate correctly; the relation-specific logic (``update_relation`` identity pin,
``remove_type_from_relations`` cascade, ``get_added_and_removed_fields`` diff) is tested directly.
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.manager.relations_manager import RelationsManager
from cmdb.models.relation_model import CmdbRelation
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_PUBLIC_ID: int = 42
FORGED_PUBLIC_ID: int = 999
NEW_RELATION_ID: int = 7
REMOVED_TYPE_ID: int = 99

SAMPLE_RELATION: dict[str, Any] = {'public_id': RELATION_PUBLIC_ID, 'relation_name': 'r'}

RELATION_OBJ_DATA: dict[str, Any] = {
    'public_id': FORGED_PUBLIC_ID,
    'relation_name': 'r',
    'parent_type_ids': [1],
    'child_type_ids': [2],
    'relation_name_parent': 'is-parent-of',
    'relation_name_child': 'is-child-of',
}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a RelationsManager instance."""
    return MagicMock(spec=RelationsManager)


def _relation_with_fields(*field_names: str) -> dict[str, Any]:
    """Builds a relation dict whose single section references the given field identifiers."""
    return {'sections': [{'name': 's1', 'fields': list(field_names)}]}


# ----------------------------------------------------- insert_relation ---------------------------------------------- #

class TestInsertRelation:
    """insert_relation forwards to the generic insert_item."""

    def test_delegates_to_insert_item(self) -> None:
        """The payload is forwarded to insert_item and its result returned."""
        mgr = _mock_manager()
        mgr.insert_item.return_value = NEW_RELATION_ID

        result = RelationsManager.insert_relation(mgr, SAMPLE_RELATION)

        assert result == NEW_RELATION_ID
        mgr.insert_item.assert_called_once_with(SAMPLE_RELATION)


# ------------------------------------------------------ get_relation ------------------------------------------------ #

class TestGetRelation:
    """get_relation forwards to the generic get_item (raw dict)."""

    def test_delegates_to_get_item_as_dict(self) -> None:
        """get_relation fetches the raw document via get_item(as_dict=True)."""
        mgr = _mock_manager()
        mgr.get_item.return_value = SAMPLE_RELATION

        assert RelationsManager.get_relation(mgr, RELATION_PUBLIC_ID) == SAMPLE_RELATION
        mgr.get_item.assert_called_once_with(RELATION_PUBLIC_ID, as_dict=True)


# --------------------------------------------------------- iterate -------------------------------------------------- #

class TestIterate:
    """iterate forwards to the generic iterate_items."""

    def test_delegates_to_iterate_items(self) -> None:
        """iterate forwards the builder params to iterate_items and returns its result."""
        mgr = _mock_manager()
        sentinel = MagicMock(name='iteration_result')
        mgr.iterate_items.return_value = sentinel
        builder_params = MagicMock(name='builder_params')

        assert RelationsManager.iterate(mgr, builder_params) is sentinel
        mgr.iterate_items.assert_called_once_with(builder_params)


# ----------------------------------------------------- update_relation ---------------------------------------------- #

class TestUpdateRelation:
    """update_relation pins the identity and forwards to the generic update_item."""

    def test_pins_public_id_and_delegates(self) -> None:
        """A forged payload public_id is overwritten with the URL id before update_item."""
        mgr = _mock_manager()
        data = {'public_id': FORGED_PUBLIC_ID, 'relation_name': 'r'}

        RelationsManager.update_relation(mgr, RELATION_PUBLIC_ID, data)

        mgr.update_item.assert_called_once_with(RELATION_PUBLIC_ID, data)
        assert data['public_id'] == RELATION_PUBLIC_ID

    def test_serializes_model_instance_then_pins(self) -> None:
        """A CmdbRelation instance is serialized to json and its identity pinned to the URL id."""
        mgr = _mock_manager()
        relation = CmdbRelation.from_data(RELATION_OBJ_DATA)

        RelationsManager.update_relation(mgr, RELATION_PUBLIC_ID, relation)

        called_id, called_data = mgr.update_item.call_args.args
        assert called_id == RELATION_PUBLIC_ID
        assert called_data['public_id'] == RELATION_PUBLIC_ID
        assert called_data['relation_name'] == 'r'


# ------------------------------------------------- remove_type_from_relations --------------------------------------- #

class TestRemoveTypeFromRelations:
    """remove_type_from_relations issues a single server-side update_many."""

    def test_pulls_type_id_from_parent_and_child_lists(self) -> None:
        """A single update_many pulls the type id from both parent and child id lists."""
        mgr = _mock_manager()

        RelationsManager.remove_type_from_relations(mgr, REMOVED_TYPE_ID)

        mgr.update_many.assert_called_once_with(
            criteria={'$or': [{'parent_type_ids': REMOVED_TYPE_ID}, {'child_type_ids': REMOVED_TYPE_ID}]},
            update={'$pull': {'parent_type_ids': REMOVED_TYPE_ID, 'child_type_ids': REMOVED_TYPE_ID}},
            plain=True,
        )


# ----------------------------------------------------- delete_relation ---------------------------------------------- #

class TestDeleteRelation:
    """delete_relation forwards to the generic delete_item."""

    def test_delegates_to_delete_item(self) -> None:
        """delete_relation forwards the public_id to delete_item and returns its result."""
        mgr = _mock_manager()
        mgr.delete_item.return_value = True

        assert RelationsManager.delete_relation(mgr, RELATION_PUBLIC_ID) is True
        mgr.delete_item.assert_called_once_with(RELATION_PUBLIC_ID)


# ----------------------------------------------- get_added_and_removed_fields --------------------------------------- #

class TestGetAddedAndRemovedFields:
    """get_added_and_removed_fields computes the section/field diff (pure)."""

    def test_detects_added_and_removed_fields(self) -> None:
        """Fields only in new are 'added'; fields only in old are 'removed'."""
        old_relation = _relation_with_fields('a', 'b')
        new_relation = _relation_with_fields('b', 'c')

        result = RelationsManager.get_added_and_removed_fields(_mock_manager(), old_relation, new_relation)

        assert set(result['added']) == {'c'}
        assert set(result['removed']) == {'a'}

    def test_no_change_yields_empty_lists(self) -> None:
        """Identical field sets produce empty added/removed lists."""
        relation = _relation_with_fields('a', 'b')

        result = RelationsManager.get_added_and_removed_fields(_mock_manager(), relation, dict(relation))

        assert result == {'added': [], 'removed': []}

    def test_missing_sections_are_treated_as_empty(self) -> None:
        """A relation without 'sections' contributes no fields."""
        result = RelationsManager.get_added_and_removed_fields(_mock_manager(), {}, _relation_with_fields('x'))

        assert set(result['added']) == {'x'}
        assert result['removed'] == []
