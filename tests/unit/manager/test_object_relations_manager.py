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
Unit tests for cmdb.manager.object_relations_manager.ObjectRelationsManager

Pure tests: no Mongo. ObjectRelationsManager is a GenericManager subclass, so the CRUD methods are
thin forwarders to the generic item-level CRUD (insert_item / get_item / iterate_items /
update_item / delete_item) - those primitives and their error wrapping are covered by the
GenericManager suite. Here each method is invoked unbound against a
``MagicMock(spec=ObjectRelationsManager)`` and asserted to delegate correctly; the object-relation
specific logic (``update_object_relation`` identity pin, the ``delete_invalidated_object_relations``
single delete, the ``update_changed_fields`` pipeline) is tested directly.
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.manager.object_relations_manager import (
    ObjectRelationsManager,
    RELATION_ID_FIELD,
    RELATION_PARENT_ID_FIELD,
    RELATION_CHILD_ID_FIELD,
    RELATION_PARENT_TYPE_ID_FIELD,
    RELATION_CHILD_TYPE_ID_FIELD,
    FIELD_VALUES_FIELD,
    PUBLIC_ID_FIELD,
)
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_RELATION_PUBLIC_ID: int = 42
FORGED_PUBLIC_ID: int = 999
NEW_OBJECT_RELATION_ID: int = 7
RELATION_ID: int = 5
PARENT_OBJECT_ID: int = 100
CHILD_OBJECT_ID: int = 200

SAMPLE_OBJECT_RELATION: dict[str, Any] = {'public_id': OBJECT_RELATION_PUBLIC_ID, 'relation_id': RELATION_ID}

OBJECT_RELATION_OBJ_DATA: dict[str, Any] = {
    'public_id': FORGED_PUBLIC_ID,
    'relation_id': RELATION_ID,
    'relation_parent_id': PARENT_OBJECT_ID,
    'relation_parent_type_id': 1,
    'relation_child_id': CHILD_OBJECT_ID,
    'relation_child_type_id': 2,
    'author_id': 1,
    'field_values': [{'name': 'a', 'value': 'x'}],
}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for an ObjectRelationsManager instance."""
    return MagicMock(spec=ObjectRelationsManager)


# ------------------------------------------------- insert_object_relation ------------------------------------------- #

class TestInsertObjectRelation:
    """insert_object_relation forwards to the generic insert_item."""

    def test_delegates_to_insert_item(self) -> None:
        """The payload is forwarded to insert_item and its result returned."""
        mgr = _mock_manager()
        mgr.insert_item.return_value = NEW_OBJECT_RELATION_ID

        result = ObjectRelationsManager.insert_object_relation(mgr, SAMPLE_OBJECT_RELATION)

        assert result == NEW_OBJECT_RELATION_ID
        mgr.insert_item.assert_called_once_with(SAMPLE_OBJECT_RELATION)


# -------------------------------------------------- get_object_relation --------------------------------------------- #

class TestGetObjectRelation:
    """get_object_relation forwards to the generic get_item (raw dict)."""

    def test_delegates_to_get_item_as_dict(self) -> None:
        """get_object_relation fetches the raw document via get_item(as_dict=True)."""
        mgr = _mock_manager()
        mgr.get_item.return_value = SAMPLE_OBJECT_RELATION

        assert ObjectRelationsManager.get_object_relation(mgr, OBJECT_RELATION_PUBLIC_ID) == SAMPLE_OBJECT_RELATION
        mgr.get_item.assert_called_once_with(OBJECT_RELATION_PUBLIC_ID, as_dict=True)


# --------------------------------------------------------- iterate -------------------------------------------------- #

class TestIterate:
    """iterate forwards to the generic iterate_items."""

    def test_delegates_to_iterate_items(self) -> None:
        """iterate forwards the builder params to iterate_items and returns its result."""
        mgr = _mock_manager()
        sentinel = MagicMock(name='iteration_result')
        mgr.iterate_items.return_value = sentinel
        builder_params = MagicMock(name='builder_params')

        assert ObjectRelationsManager.iterate(mgr, builder_params) is sentinel
        mgr.iterate_items.assert_called_once_with(builder_params)


# ------------------------------------------------- get_related_relations -------------------------------------------- #

class TestGetRelatedRelations:
    """get_related_relations finds every object relation referencing the object."""

    def test_finds_with_related_query(self) -> None:
        """The method queries find() with the related-relations query and returns a list."""
        mgr = _mock_manager()
        query = {'$or': [{RELATION_PARENT_ID_FIELD: PARENT_OBJECT_ID}, {RELATION_CHILD_ID_FIELD: PARENT_OBJECT_ID}]}
        mgr.get_related_relations_query.return_value = query
        mgr.find.return_value = [SAMPLE_OBJECT_RELATION]

        result = ObjectRelationsManager.get_related_relations(mgr, PARENT_OBJECT_ID)

        assert result == [SAMPLE_OBJECT_RELATION]
        mgr.find.assert_called_once_with(criteria=query)


# ----------------------------------------------- get_related_relations_query ---------------------------------------- #

class TestGetRelatedRelationsQuery:
    """get_related_relations_query builds the parent/child $or query (pure)."""

    def test_builds_or_on_parent_and_child(self) -> None:
        """The query matches the object id on either the parent or child object field."""
        result = ObjectRelationsManager.get_related_relations_query(_mock_manager(), PARENT_OBJECT_ID)

        assert result == {
            '$or': [
                {RELATION_PARENT_ID_FIELD: PARENT_OBJECT_ID},
                {RELATION_CHILD_ID_FIELD: PARENT_OBJECT_ID},
            ]
        }


# ------------------------------------------------ update_object_relation -------------------------------------------- #

class TestUpdateObjectRelation:
    """update_object_relation pins the identity and forwards to the generic update_item."""

    def test_pins_public_id_on_dict_and_delegates(self) -> None:
        """A forged payload public_id is overwritten with the URL id before update_item."""
        mgr = _mock_manager()
        data = {'public_id': FORGED_PUBLIC_ID, 'relation_id': RELATION_ID}

        ObjectRelationsManager.update_object_relation(mgr, OBJECT_RELATION_PUBLIC_ID, data)

        mgr.update_item.assert_called_once_with(OBJECT_RELATION_PUBLIC_ID, data)
        assert data[PUBLIC_ID_FIELD] == OBJECT_RELATION_PUBLIC_ID

    def test_serializes_model_instance_then_pins(self) -> None:
        """A CmdbObjectRelation instance is serialized to json and its identity pinned to the URL id."""
        mgr = _mock_manager()
        object_relation = CmdbObjectRelation.from_data(OBJECT_RELATION_OBJ_DATA)

        ObjectRelationsManager.update_object_relation(mgr, OBJECT_RELATION_PUBLIC_ID, object_relation)

        called_id, called_data = mgr.update_item.call_args.args
        assert called_id == OBJECT_RELATION_PUBLIC_ID
        assert isinstance(called_data, dict)
        assert called_data[PUBLIC_ID_FIELD] == OBJECT_RELATION_PUBLIC_ID


# ------------------------------------------------ delete_object_relation -------------------------------------------- #

class TestDeleteObjectRelation:
    """delete_object_relation forwards to the generic delete_item."""

    def test_delegates_to_delete_item(self) -> None:
        """delete_object_relation forwards the public_id to delete_item and returns its result."""
        mgr = _mock_manager()
        mgr.delete_item.return_value = True

        assert ObjectRelationsManager.delete_object_relation(mgr, OBJECT_RELATION_PUBLIC_ID) is True
        mgr.delete_item.assert_called_once_with(OBJECT_RELATION_PUBLIC_ID)


# ------------------------------------------- delete_invalidated_object_relations ------------------------------------ #

class TestDeleteInvalidatedObjectRelations:
    """delete_invalidated_object_relations issues a single server-side delete_many (no N+1 loop)."""

    def test_deletes_by_parent_type_ids_in_one_call(self) -> None:
        """With is_parent_ids=True a single delete_many targets the parent type id field."""
        mgr = _mock_manager()
        invalid_ids = [3, 4]

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, invalid_ids, True)

        mgr.delete_many.assert_called_once_with({
            '$and': [
                {RELATION_ID_FIELD: RELATION_ID},
                {RELATION_PARENT_TYPE_ID_FIELD: {'$in': invalid_ids}},
            ]
        })

    def test_deletes_by_child_type_ids_in_one_call(self) -> None:
        """With is_parent_ids=False a single delete_many targets the child type id field."""
        mgr = _mock_manager()
        invalid_ids = [9]

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, invalid_ids, False)

        mgr.delete_many.assert_called_once_with({
            '$and': [
                {RELATION_ID_FIELD: RELATION_ID},
                {RELATION_CHILD_TYPE_ID_FIELD: {'$in': invalid_ids}},
            ]
        })


# ----------------------------------------------------- update_changed_fields --------------------------------------- #

class TestUpdateChangedFields:
    """update_changed_fields applies the field diff in a single pipeline update_many."""

    def test_no_change_skips_the_write(self) -> None:
        """Empty added/removed lists must not issue any database write."""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {'added': [], 'removed': []})

        mgr.update_many.assert_not_called()

    def test_missing_keys_skip_the_write(self) -> None:
        """A diff missing both keys is treated as no change."""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {})

        mgr.update_many.assert_not_called()

    def test_builds_pipeline_filtering_removed_and_appending_added(self) -> None:
        """The pipeline filters removed names and appends new {name, value: None} entries."""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {'added': ['new'], 'removed': ['old']})

        criteria, pipeline = mgr.update_many.call_args.args
        assert criteria == {RELATION_ID_FIELD: RELATION_ID}
        assert mgr.update_many.call_args.kwargs == {'plain': True}

        set_stage = pipeline[0]['$set'][FIELD_VALUES_FIELD]['$concatArrays']
        filter_cond = set_stage[0]['$filter']['cond']
        appended = set_stage[1]

        # removed names are excluded via $not / $in
        assert filter_cond == {'$not': [{'$in': ['$$fv.name', ['old']]}]}
        # added names are appended with an empty value
        assert appended == [{'name': 'new', 'value': None}]
