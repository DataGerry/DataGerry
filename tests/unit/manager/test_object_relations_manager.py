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
read-then-atomic-delete walk, the ``update_changed_fields`` pipeline) is tested directly.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.object_relations_manager import ObjectRelationsManager, field_values_after
from cmdb.models.object_relation_model import (
    CmdbObjectRelation,
    ObjectRelationKey,
    ObjectRelationRole,
)
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerIterationError
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


# -------------------------------------------- get_relations_of_objects_query ---------------------------------------- #

class TestGetRelationsOfObjectsQuery:
    """get_relations_of_objects_query matches any of several objects as parent or child (pure)."""

    def test_builds_an_or_of_two_in_clauses(self) -> None:
        """Every id is accepted on the parent field and on the child field"""
        ids = [PARENT_OBJECT_ID, PARENT_OBJECT_ID + 1]

        result = ObjectRelationsManager.get_relations_of_objects_query(_mock_manager(), ids)

        assert result == {
            '$or': [
                {ObjectRelationKey.RELATION_PARENT_ID.value: {'$in': ids}},
                {ObjectRelationKey.RELATION_CHILD_ID.value: {'$in': ids}},
            ]
        }

    def test_an_empty_list_builds_two_empty_in_clauses(self) -> None:
        """No id, nothing to match: the clauses stay ``$in: []`` rather than being dropped"""
        result = ObjectRelationsManager.get_relations_of_objects_query(_mock_manager(), [])

        assert result == {
            '$or': [
                {ObjectRelationKey.RELATION_PARENT_ID.value: {'$in': []}},
                {ObjectRelationKey.RELATION_CHILD_ID.value: {'$in': []}},
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
        assert data[ObjectRelationKey.PUBLIC_ID.value] == OBJECT_RELATION_PUBLIC_ID

    def test_serializes_model_instance_then_pins(self) -> None:
        """A CmdbObjectRelation instance is serialized to json and its identity pinned to the URL id."""
        mgr = _mock_manager()
        object_relation = CmdbObjectRelation.from_data(OBJECT_RELATION_OBJ_DATA)

        ObjectRelationsManager.update_object_relation(mgr, OBJECT_RELATION_PUBLIC_ID, object_relation)

        called_id, called_data = mgr.update_item.call_args.args
        assert called_id == OBJECT_RELATION_PUBLIC_ID
        assert isinstance(called_data, dict)
        assert called_data[ObjectRelationKey.PUBLIC_ID.value] == OBJECT_RELATION_PUBLIC_ID


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
    """
    delete_invalidated_object_relations reads the matching ids, then removes each with an atomic read-and-delete

    The documents collected are the ones each call deleted - the history is written from them
    """

    @staticmethod
    def _manager() -> MagicMock:
        """A spec'd manager whose criteria builder is the real one - it is a pure function"""
        mgr = _mock_manager()
        mgr._invalidated_criteria.side_effect = ObjectRelationsManager._invalidated_criteria
        return mgr

    @staticmethod
    def _criteria(type_key: ObjectRelationKey, invalid_ids: list[int]) -> dict:
        """The match the method builds for one side."""
        return {'$and': [{ObjectRelationKey.RELATION_ID.value: RELATION_ID},
                         {type_key.value: {'$in': invalid_ids}}]}

    @pytest.mark.parametrize('is_parent_ids,type_key', [
        pytest.param(True, ObjectRelationKey.RELATION_PARENT_TYPE_ID, id='parent side'),
        pytest.param(False, ObjectRelationKey.RELATION_CHILD_TYPE_ID, id='child side'),
    ])
    def test_reads_the_ids_on_the_side_stamped_type(self, is_parent_ids: bool, type_key: ObjectRelationKey) -> None:
        """The read matches the relation id and the side's stamped type id, and projects the public_id only"""
        mgr = self._manager()
        mgr.find.return_value = []
        invalid_ids = [3, 4]

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, invalid_ids, is_parent_ids, [])

        mgr.find.assert_called_once_with(self._criteria(type_key, invalid_ids),
                                         projection={ObjectRelationKey.PUBLIC_ID.value: 1})
        mgr.delete_many.assert_not_called()

    def test_each_id_is_deleted_with_the_match_and_collected(self) -> None:
        """One find_one_and_delete per id, still carrying the match; the deleted documents land in `deleted`"""
        mgr = self._manager()
        mgr.find.return_value = [{ObjectRelationKey.PUBLIC_ID.value: 11}, {ObjectRelationKey.PUBLIC_ID.value: 12}]
        first, second = {ObjectRelationKey.PUBLIC_ID.value: 11}, {ObjectRelationKey.PUBLIC_ID.value: 12}
        mgr.find_one_and_delete.side_effect = [first, second]
        deleted: list = []

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, [3], True, deleted)

        criteria = self._criteria(ObjectRelationKey.RELATION_PARENT_TYPE_ID, [3])
        assert [call.args[0] for call in mgr.find_one_and_delete.call_args_list] == [
            {'$and': [criteria, {ObjectRelationKey.PUBLIC_ID.value: 11}]},
            {'$and': [criteria, {ObjectRelationKey.PUBLIC_ID.value: 12}]},
        ]
        assert deleted == [first, second]

    def test_an_instance_gone_in_between_is_not_collected(self) -> None:
        """Another writer deleted (or re-pointed) it first: nothing deleted, nothing to record"""
        mgr = self._manager()
        mgr.find.return_value = [{ObjectRelationKey.PUBLIC_ID.value: 11}, {ObjectRelationKey.PUBLIC_ID.value: 12}]
        kept = {ObjectRelationKey.PUBLIC_ID.value: 12}
        mgr.find_one_and_delete.side_effect = [None, kept]
        deleted: list = []

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, [3], False, deleted)

        assert deleted == [kept]

    def test_a_failed_delete_keeps_what_was_deleted_before_it(self) -> None:
        """The error propagates; `deleted` still holds the documents removed ahead of it"""
        mgr = self._manager()
        mgr.find.return_value = [{ObjectRelationKey.PUBLIC_ID.value: 11}, {ObjectRelationKey.PUBLIC_ID.value: 12}]
        first = {ObjectRelationKey.PUBLIC_ID.value: 11}
        mgr.find_one_and_delete.side_effect = [first, BaseManagerDeleteError('boom')]
        deleted: list = []

        with pytest.raises(BaseManagerDeleteError):
            ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, [3], True, deleted)

        assert deleted == [first]

    def test_an_empty_id_list_issues_no_round_trip(self) -> None:
        """
        Nothing to invalidate costs no round trip

        A '$in' over an empty list matches nothing, so the read could only ever answer nothing - the
        same early return the port and cascade managers make.
        """
        mgr = self._manager()

        ObjectRelationsManager.delete_invalidated_object_relations(mgr, RELATION_ID, [], True, [])

        mgr.find.assert_not_called()
        mgr.find_one_and_delete.assert_not_called()


# ------------------------------------------------------- the relation tabs ----------------------------------------- #

class TestRelationTabs:
    """
    The two reads behind the lazily-loaded relation tabs

    Both wrap the database layer's typed failure into the manager's own iteration error - the tab strip is
    loaded on its own, so a failure here has to be reportable as this surface's failure rather than
    escaping as a driver exception.
    """

    def test_the_tabs_come_from_one_aggregation(self) -> None:
        """The descriptors are computed server-side, not by loading the instances"""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = [{'relation_id': RELATION_ID}]

        tabs = ObjectRelationsManager.get_relation_tabs(mgr, PARENT_OBJECT_ID)

        assert tabs == [{'relation_id': RELATION_ID}]
        mgr.aggregate_all.assert_called_once()

    def test_a_failing_tab_aggregation_is_wrapped(self) -> None:
        """A database failure surfaces as the manager's own error type"""
        mgr = _mock_manager()
        cause = BaseManagerIterationError('boom')
        mgr.aggregate_all.side_effect = cause

        with pytest.raises(ObjectRelationsManagerIterationError) as raised:
            ObjectRelationsManager.get_relation_tabs(mgr, PARENT_OBJECT_ID)

        assert raised.value.__cause__ is cause

    def test_a_bug_in_the_tab_aggregation_propagates_as_itself(self) -> None:
        """A programming error is not a database failure: it reaches the route's 500 unwrapped"""
        mgr = _mock_manager()
        mgr.aggregate_all.side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            ObjectRelationsManager.get_relation_tabs(mgr, PARENT_OBJECT_ID)

    @pytest.mark.parametrize(
        'role, side_field',
        [(ObjectRelationRole.PARENT.value, ObjectRelationKey.RELATION_PARENT_ID.value),
         (ObjectRelationRole.CHILD.value, ObjectRelationKey.RELATION_CHILD_ID.value)],
        ids=['parent', 'child'],
    )
    def test_the_role_picks_the_side(self, role: str, side_field: str) -> None:
        """A tab is (relation_id, role), and the role is which side of the relation the object is on"""
        mgr = _mock_manager()
        mgr.count_documents.return_value = 2
        mgr.find.return_value = []

        ObjectRelationsManager.get_relation_tab_instances(mgr, PARENT_OBJECT_ID, RELATION_ID, role)

        assert mgr.find.call_args.kwargs['criteria'] == {
            ObjectRelationKey.RELATION_ID.value: RELATION_ID,
            side_field: PARENT_OBJECT_ID,
        }

    def test_an_unknown_role_is_refused(self) -> None:
        """
        The two sides are a choice, not a default

        Reading anything that is not 'parent' as 'child' would answer a typo with the OTHER tab's
        instances - a wrong result that looks like a valid one. The route validates the parameter too;
        this is the manager's own contract.
        """
        mgr = _mock_manager()

        with pytest.raises(ObjectRelationsManagerIterationError):
            ObjectRelationsManager.get_relation_tab_instances(mgr, PARENT_OBJECT_ID, RELATION_ID, 'bogus')

        mgr.count_documents.assert_not_called()
        mgr.find.assert_not_called()

    def test_the_total_is_the_group_count_not_the_page(self) -> None:
        """The badge counts the whole group; only the requested page is materialised"""
        mgr = _mock_manager()
        mgr.count_documents.return_value = 17
        mgr.find.return_value = [SAMPLE_OBJECT_RELATION]

        instances, total = ObjectRelationsManager.get_relation_tab_instances(
            mgr, PARENT_OBJECT_ID, RELATION_ID, ObjectRelationRole.PARENT.value, limit=1,
        )

        assert (instances, total) == ([SAMPLE_OBJECT_RELATION], 17)

    @pytest.mark.parametrize('failing', ['count_documents', 'find'])
    def test_a_failing_instance_read_is_wrapped(self, failing: str) -> None:
        """A database failure of either read surfaces as the manager's own error type"""
        mgr = _mock_manager()
        mgr.count_documents.return_value = 1
        mgr.find.return_value = []
        cause = BaseManagerGetError('boom')
        getattr(mgr, failing).side_effect = cause

        with pytest.raises(ObjectRelationsManagerIterationError) as raised:
            ObjectRelationsManager.get_relation_tab_instances(
                mgr, PARENT_OBJECT_ID, RELATION_ID, ObjectRelationRole.PARENT.value,
            )

        assert raised.value.__cause__ is cause

    def test_a_bug_in_the_instance_read_propagates_as_itself(self) -> None:
        """A programming error is not a database failure: it reaches the route's 500 unwrapped"""
        mgr = _mock_manager()
        mgr.count_documents.side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            ObjectRelationsManager.get_relation_tab_instances(
                mgr, PARENT_OBJECT_ID, RELATION_ID, ObjectRelationRole.PARENT.value,
            )


# ----------------------------------------------------- update_changed_fields --------------------------------------- #

class TestUpdateChangedFields:
    """update_changed_fields applies the field diff in a single pipeline update (update_many_raw)."""

    def test_no_change_skips_the_write(self) -> None:
        """Empty added/removed lists must not issue any database write."""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {'added': [], 'removed': []})

        mgr.update_many_raw.assert_not_called()

    def test_missing_keys_skip_the_write(self) -> None:
        """A diff missing both keys is treated as no change."""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {})

        mgr.update_many_raw.assert_not_called()

    def test_one_pipeline_update_scoped_to_the_relation(self) -> None:
        """One update_many_raw on the relation's instances, setting field_values to field_values_after(...)"""
        mgr = _mock_manager()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {'added': ['new'], 'removed': ['old']})

        criteria, pipeline = mgr.update_many_raw.call_args.args
        assert criteria == {ObjectRelationKey.RELATION_ID.value: RELATION_ID}
        assert pipeline == [{'$set': {ObjectRelationKey.FIELD_VALUES.value: field_values_after(['new'], ['old'])}}]
        mgr.update_many.assert_not_called()


class TestFieldValuesAfter:
    """The expression an instance's field_values becomes: kept entries, then the added names it does not hold"""

    def test_the_kept_entries_drop_the_removed_names(self) -> None:
        """The stored list (missing read as empty) without the removed names"""
        kept = field_values_after(['new'], ['old'])['$concatArrays'][0]['$filter']

        assert kept['input'] == {'$ifNull': ['$field_values', []]}
        assert kept['cond'] == {'$not': [{'$in': ['$$fv.name', ['old']]}]}

    def test_an_added_name_is_appended_null_only_where_it_is_not_held(self) -> None:
        """The added entries are a literal, filtered by the names the stored list already holds"""
        appended = field_values_after(['new', 'other'], [])['$concatArrays'][1]['$filter']

        assert appended['input'] == {'$literal': [{'name': 'new', 'value': None}, {'name': 'other', 'value': None}]}
        assert appended['cond'] == {'$not': [{'$in': ['$$nf.name', {'$map': {
            'input': {'$ifNull': ['$field_values', []]}, 'as': 'held', 'in': '$$held.name',
        }}]}]}


# ------------------------------------------------- the retyped reset + the instance read ---------------------------- #

class TestRetypedFields:
    """update_changed_fields / field_values_after reset a retyped field's value"""

    def test_a_retyped_field_alone_writes(self) -> None:
        """No add, no remove - still one pipeline update"""
        mgr = MagicMock()

        ObjectRelationsManager.update_changed_fields(mgr, RELATION_ID, {'retyped': ['typed']})

        filter_, pipeline = mgr.update_many_raw.call_args.args
        assert filter_ == {ObjectRelationKey.RELATION_ID.value: RELATION_ID}
        assert pipeline == [{'$set': {
            ObjectRelationKey.FIELD_VALUES.value: field_values_after([], [], ['typed']),
        }}]

    def test_the_kept_entries_are_mapped_to_null_for_retyped_names(self) -> None:
        """The removal filter is the map's input; other entries pass unchanged"""
        kept: dict[str, Any] = field_values_after([], ['old'], ['typed'])['$concatArrays'][0]

        mapped: dict[str, Any] = kept['$map']
        assert mapped['input']['$filter']['cond'] == {'$not': [{'$in': ['$$fv.name', ['old']]}]}
        assert mapped['in'] == {'$cond': [
            {'$in': ['$$kv.name', ['typed']]}, {'name': '$$kv.name', 'value': None}, '$$kv',
        ]}

    def test_no_retyped_keeps_the_plain_filter(self) -> None:
        """The expression without a reset is unchanged"""
        assert '$filter' in field_values_after(['new'], ['old'])['$concatArrays'][0]


class TestRelationHasInstances:
    """relation_has_instances - one count stopping at the first match"""

    @pytest.mark.parametrize('count, expected', [(0, False), (1, True)], ids=['none', 'some'])
    def test_answers_from_a_limited_count(self, count: int, expected: bool) -> None:
        """limit=1 on the relation's instances"""
        mgr = MagicMock()
        mgr.count_documents.return_value = count

        assert ObjectRelationsManager.relation_has_instances(mgr, RELATION_ID) is expected
        mgr.count_documents.assert_called_once_with({ObjectRelationKey.RELATION_ID.value: RELATION_ID}, limit=1)

    def test_a_failed_count_propagates(self) -> None:
        """The route guard answers it"""
        mgr = MagicMock()
        mgr.count_documents.side_effect = BaseManagerGetError('down')

        with pytest.raises(BaseManagerGetError):
            ObjectRelationsManager.relation_has_instances(mgr, RELATION_ID)
