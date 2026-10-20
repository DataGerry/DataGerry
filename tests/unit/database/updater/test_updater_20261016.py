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
Unit tests for cmdb.database.updater.versions.updater_20261016

The migration removes every CmdbObjectRelation whose (relation, parent, child) an instance with a lower public_id
holds, records each removal in its history with the field values, then builds the unique `relation_pair` index. Its
run against a real collection is its own integration test; this module owns the frozen literals, the choice of what
goes, the history entry, that an entry is written once, the index branches, the order and the failure tail
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261016 as module
from cmdb.database.updater.versions.updater_20261016 import Update20261016, extra_instance_ids, removal_log_entry
from cmdb.errors.updater import UpdaterException
from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction
from cmdb.models.log_model.object_relation_log_constants import ObjectRelationLogKey
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.models.object_relation_model.object_relation_constants import (
    OBJECT_RELATION_PAIR_INDEX,
    ObjectRelationFieldValueKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261016
DATABASE_NAME: str = 'cmdb-unit'
NOW: datetime = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
KEPT_ID: int = 3
EXTRA_IDS: list[int] = [7, 9]


def _instance(public_id: int, field_values: Any = None) -> dict[str, Any]:
    """A stored instance of the duplicated pair"""
    return {'public_id': public_id, 'relation_id': 1, 'relation_parent_id': 10, 'relation_child_id': 20,
            'field_values': field_values if field_values is not None else [{'name': 'port', 'value': str(public_id)}]}


def _updater(groups: list[dict[str, Any]] | None = None, instances: list[dict[str, Any]] | None = None,
             logged_before: dict[str, Any] | None = None,
             index_info: dict[str, Any] | None = None) -> tuple[Update20261016, MagicMock]:
    """The migration over a mocked database manager"""
    dbm = MagicMock()
    dbm.aggregate_all.return_value = list(groups or [])
    dbm.find.return_value = iter(instances or [])
    dbm.get_collection.return_value.find_one.return_value = logged_before
    dbm.get_index_info.return_value = index_info or {}
    updater = Update20261016.__new__(Update20261016)
    updater.dbm = dbm
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.OBJECT_RELATION_COLLECTION, CmdbObjectRelation.COLLECTION),
    (module.OBJECT_RELATION_LOG_COLLECTION, CmdbObjectRelationLog.COLLECTION),
    (module.PUBLIC_ID_FIELD, ObjectRelationKey.PUBLIC_ID.value),
    (module.PAIR_FIELDS, (ObjectRelationKey.RELATION_ID.value, ObjectRelationKey.RELATION_PARENT_ID.value,
                          ObjectRelationKey.RELATION_CHILD_ID.value)),
    (module.FIELD_VALUES_FIELD, ObjectRelationKey.FIELD_VALUES.value),
    (module.FIELD_VALUE_NAME, ObjectRelationFieldValueKey.NAME.value),
    (module.FIELD_VALUE_VALUE, ObjectRelationFieldValueKey.VALUE.value),
    (module.PAIR_INDEX, OBJECT_RELATION_PAIR_INDEX),
    (module.LOG_ACTION_DELETE, LogInteraction.DELETE.value),
    ((module.LOG_ACTION, module.LOG_CREATION_TIME, module.LOG_AUTHOR_ID, module.LOG_AUTHOR_NAME,
      module.LOG_OBJECT_RELATION_ID, module.LOG_PARENT_ID, module.LOG_CHILD_ID, module.LOG_CHANGES),
     tuple(key.value for key in (ObjectRelationLogKey.ACTION, ObjectRelationLogKey.CREATION_TIME,
                                 ObjectRelationLogKey.AUTHOR_ID, ObjectRelationLogKey.AUTHOR_NAME,
                                 ObjectRelationLogKey.OBJECT_RELATION_ID,
                                 ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID,
                                 ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID, ObjectRelationLogKey.CHANGES))),
], ids=['collection', 'log-collection', 'public-id', 'pair', 'field-values', 'value-name', 'value-value', 'index',
        'delete', 'log-keys'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


def test_the_frozen_index_is_the_one_the_model_declares() -> None:
    """Same keys, same order, unique"""
    declared = next(index for index in CmdbObjectRelation.get_index_keys()
                    if index.document['name'] == module.PAIR_INDEX)

    assert tuple(declared.document['key']) == module.PAIR_FIELDS and declared.document['unique'] is True


class TestExtraInstanceIds:
    """extra_instance_ids"""

    def test_all_but_the_lowest_of_each_pair(self) -> None:
        """Across pairs, ascending"""
        groups = [{'ids': [9, KEPT_ID, 7]}, {'ids': [12, 4]}]

        assert extra_instance_ids(groups) == [7, 9, 12]

    @pytest.mark.parametrize('ids', [[None, 'x', True, 5], [5]])
    def test_an_id_that_is_no_int_is_never_chosen(self, ids: list[Any]) -> None:
        """Only ints are removed; a lone int keeps its pair"""
        assert not extra_instance_ids([{'ids': ids}])

    def test_no_groups_nothing_to_remove(self) -> None:
        """A collection without duplicates"""
        assert not extra_instance_ids([]) and not extra_instance_ids([{'ids': None}])


class TestRemovalLogEntry:
    """removal_log_entry"""

    def test_a_delete_entry_keeping_the_field_values(self) -> None:
        """Name -> value, the CREATE shape - the only record of values nobody chose to delete"""
        entry = removal_log_entry(_instance(7, [{'name': 'port', 'value': 'eth0'}, {'name': 'speed'}]), NOW)

        assert entry == {
            'action': 'DELETE', 'creation_time': NOW, 'author_id': None, 'author_name': module.UPDATE_AUTHOR_NAME,
            'object_relation_parent_id': 10, 'object_relation_child_id': 20, 'object_relation_id': 7,
            'changes': {'port': 'eth0', 'speed': None},
        }

    @pytest.mark.parametrize('field_values', ['x', [None, {'value': 1}, {'name': 3}], []])
    def test_unusable_field_values_are_skipped(self, field_values: Any) -> None:
        """Nothing invented"""
        assert removal_log_entry(_instance(7, field_values), NOW)['changes'] == {}


class TestRemoveDuplicates:
    """Update20261016.remove_duplicates"""

    def test_each_extra_is_recorded_then_deleted(self) -> None:
        """History first, then the delete by public_id; the kept instance is never read"""
        instances = [_instance(public_id) for public_id in EXTRA_IDS]
        updater, dbm = _updater([{'ids': [KEPT_ID, *EXTRA_IDS]}], instances)
        calls: list[Any] = []
        dbm.insert.side_effect = lambda *args: calls.append(('log', args[2]['object_relation_id']))
        dbm.delete.side_effect = lambda *args: calls.append(('delete', args[2]['public_id']))

        assert updater.remove_duplicates() == EXTRA_IDS

        assert calls == [('log', 7), ('delete', 7), ('log', 9), ('delete', 9)]
        dbm.aggregate_all.assert_called_once_with(module.OBJECT_RELATION_COLLECTION, DATABASE_NAME,
                                              module.DUPLICATE_PAIRS_PIPELINE)
        assert dbm.find.call_args.kwargs['filter'] == {'public_id': {'$in': EXTRA_IDS}}

    def test_no_duplicates_reads_nothing_more(self) -> None:
        """One aggregation, nothing written"""
        updater, dbm = _updater()

        assert updater.remove_duplicates() == []
        dbm.find.assert_not_called()
        dbm.insert.assert_not_called()
        dbm.delete.assert_not_called()


class TestRecordRemoval:
    """Update20261016.record_removal"""

    def test_written_once(self) -> None:
        """Looked up by instance and this update's author name"""
        updater, dbm = _updater()

        assert updater.record_removal(_instance(7), NOW) is True
        dbm.get_collection.return_value.find_one.assert_called_once_with(
            {'object_relation_id': 7, 'author_name': module.UPDATE_AUTHOR_NAME})
        dbm.insert.assert_called_once_with(module.OBJECT_RELATION_LOG_COLLECTION, DATABASE_NAME,
                                           removal_log_entry(_instance(7), NOW))

    def test_an_entry_from_an_interrupted_run_is_not_repeated(self) -> None:
        """The run stopped between the entry and the delete"""
        updater, dbm = _updater(logged_before={'public_id': 1})

        assert updater.record_removal(_instance(7), NOW) is False
        dbm.insert.assert_not_called()


class TestBuildUniquePairIndex:
    """Update20261016.build_unique_pair_index"""

    def test_built_when_absent(self) -> None:
        """Unique, the three keys in order"""
        updater, dbm = _updater()

        assert updater.build_unique_pair_index() is True
        index = dbm.create_indexes.call_args.args[2][0]
        assert index.document['name'] == module.PAIR_INDEX and index.document['unique'] is True
        assert tuple(index.document['key']) == module.PAIR_FIELDS
        dbm.drop_index.assert_not_called()

    def test_left_alone_when_already_unique(self) -> None:
        """A second run"""
        updater, dbm = _updater(index_info={module.PAIR_INDEX: {'unique': True}})

        assert updater.build_unique_pair_index() is False
        dbm.create_indexes.assert_not_called()

    def test_a_non_unique_one_is_dropped_and_rebuilt(self) -> None:
        """MongoDB refuses other options under the same name"""
        updater, dbm = _updater(index_info={module.PAIR_INDEX: {}})

        assert updater.build_unique_pair_index() is True
        dbm.drop_index.assert_called_once_with(module.OBJECT_RELATION_COLLECTION, DATABASE_NAME, module.PAIR_INDEX)


class TestStartUpdate:
    """Update20261016.start_update"""

    def test_the_metadata(self) -> None:
        """The date it runs at"""
        updater, _dbm = _updater()

        assert updater.creation_date() == CREATION_DATE and updater.description()

    @pytest.mark.parametrize('removed, built', [([], False), (EXTRA_IDS, True)], ids=['nothing', 'removed-built'])
    def test_removes_then_indexes_then_bumps(self, removed: list[int], built: bool) -> None:
        """In that order, whether anything was removed or built"""
        updater, _dbm = _updater()
        order = MagicMock()
        updater.remove_duplicates = order.remove
        updater.build_unique_pair_index = order.index
        updater.increase_updater_version = order.version
        order.remove.return_value = removed
        order.index.return_value = built

        updater.start_update()

        assert order.method_calls == [call.remove(), call.index(), call.version(CREATION_DATE)]

    def test_a_failure_is_wrapped_carrying_the_error(self) -> None:
        """The exception itself; the version is not bumped"""
        updater, dbm = _updater()
        error = RuntimeError('aggregate failed')
        dbm.aggregate_all.side_effect = error

        with pytest.raises(UpdaterException) as exc_info:
            updater.start_update()

        assert exc_info.value.args[0] is error
        updater.increase_updater_version.assert_not_called()
