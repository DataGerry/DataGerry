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
Unit tests for cmdb.database.updater.versions.updater_20261030

The migration reports every SpecialType more than one Type carries - each Type's id, name and object count - writes
nothing to a Type, and builds the partial unique special_type index only when no duplicate is stored. Its run
against a real collection is its own integration test; this module owns the frozen literals, the duplicate plan, the
report, the index branches, the order and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261030 as module
from cmdb.database.updater.versions.updater_20261030 import Update20261030, duplicate_special_types
from cmdb.errors.database import DocumentGetError
from cmdb.errors.updater import UpdaterException
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261030
DATABASE_NAME: str = 'cmdb-unit'
OBJECT_COUNT: int = 40
CABLE: str = SpecialType.CABLE.value
RACK: str = SpecialType.RACK.value


def _type(public_id: Any, name: Any, special_type: Any) -> dict[str, Any]:
    """A stored Type as the migration reads it."""
    return {module.PUBLIC_ID_FIELD: public_id, module.NAME_FIELD: name, module.SPECIAL_TYPE_FIELD: special_type}


def _updater(types: list[dict[str, Any]] | None = None,
             index_info: dict[str, Any] | None = None) -> tuple[Update20261030, MagicMock]:
    """The migration over a mocked database manager; every Type has OBJECT_COUNT objects"""
    dbm = MagicMock()
    dbm.find.return_value = iter(types or [])
    dbm.count.return_value = OBJECT_COUNT
    dbm.get_index_info.return_value = index_info or {}

    return Update20261030(dbm, DATABASE_NAME), dbm


class TestFrozenLiterals:
    """The literals still name what the live models declare"""

    def test_the_collections_and_fields(self) -> None:
        """The type and object collections and their keys"""
        assert (module.TYPE_COLLECTION, module.OBJECT_COLLECTION) == (CmdbType.COLLECTION, CmdbObject.COLLECTION)
        assert (module.SPECIAL_TYPE_FIELD, module.NAME_FIELD, module.PUBLIC_ID_FIELD) == (
            TypeSchemaKey.SPECIAL_TYPE.value, TypeSchemaKey.NAME.value, TypeSchemaKey.PUBLIC_ID.value)

    def test_the_index_is_the_one_the_model_declares(self) -> None:
        """Same name, same key, unique, same partial filter"""
        declared = next(index for index in CmdbType.INDEX_KEYS if index['name'] == module.SPECIAL_TYPE_INDEX)

        assert declared['keys'] == [(module.SPECIAL_TYPE_FIELD, CmdbType.DAO_ASCENDING)]
        assert declared['unique'] is True
        assert declared['partialFilterExpression'] == module.MARKER_IS_SET

    def test_creation_date(self) -> None:
        """The version this migration bumps to"""
        assert _updater()[0].creation_date() == CREATION_DATE

    def test_description_names_the_special_type(self) -> None:
        """What the update log shows"""
        assert 'SpecialType' in _updater()[0].description()


class TestDuplicateSpecialTypes:
    """duplicate_special_types"""

    def test_only_markers_held_twice_by_id(self) -> None:
        """Each with its Types ascending"""
        types = [_type(9, 'c2', CABLE), _type(3, 'c1', CABLE), _type(4, 'r', RACK)]

        assert duplicate_special_types(types) == {CABLE: [_type(3, 'c1', CABLE), _type(9, 'c2', CABLE)]}

    def test_no_duplicate_no_entry(self) -> None:
        """One Type per marker"""
        assert not duplicate_special_types([_type(1, 'c', CABLE), _type(2, 'r', RACK)])

    def test_an_unreadable_document_is_skipped(self) -> None:
        """No string marker or no int id"""
        assert not duplicate_special_types([_type(1, 'a', CABLE), _type('2', 'b', CABLE), _type(3, 'c', None)])

    def test_an_empty_marker_is_no_marker(self) -> None:
        """'' is how the schema lets an ordinary Type say it has none"""
        assert not duplicate_special_types([_type(1, 'a', ''), _type(2, 'b', '')])

    def test_the_filter_leaves_out_null_and_the_empty_string(self) -> None:
        """A non-empty string only"""
        assert module.MARKER_IS_SET == {module.SPECIAL_TYPE_FIELD: {'$gt': ''}}


class TestReportDuplicates:
    """Update20261030.report_duplicates"""

    def test_reads_only_set_markers_projected(self) -> None:
        """Ordinary Types are not read"""
        updater, dbm = _updater()

        updater.report_duplicates()

        dbm.find.assert_called_once_with(
            module.TYPE_COLLECTION, DATABASE_NAME, filter=module.MARKER_IS_SET,
            projection={module.PUBLIC_ID_FIELD: 1, module.NAME_FIELD: 1, module.SPECIAL_TYPE_FIELD: 1,
                        module.MONGO_ID_FIELD: 0})

    def test_a_duplicate_is_logged_with_ids_names_and_object_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        """For an administrator to decide which Type to delete"""
        updater, dbm = _updater([_type(3, 'c1', CABLE), _type(9, 'c2', CABLE)])

        with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
            assert list(updater.report_duplicates()) == [CABLE]

        (record,) = caplog.records
        message: str = record.getMessage()
        assert f"type 3 'c1' ({OBJECT_COUNT} objects)" in message and f"type 9 'c2' ({OBJECT_COUNT} objects)" in message
        dbm.count.assert_any_call(module.OBJECT_COLLECTION, DATABASE_NAME, {module.OBJECT_TYPE_ID_FIELD: 9})

    def test_nothing_is_written(self) -> None:
        """Report only"""
        updater, dbm = _updater([_type(3, 'c1', CABLE), _type(9, 'c2', CABLE)])

        updater.report_duplicates()

        dbm.update.assert_not_called()
        dbm.delete.assert_not_called()


class TestBuildUniqueSpecialTypeIndex:
    """Update20261030.build_unique_special_type_index"""

    def test_a_missing_index_is_built_partial(self) -> None:
        """Unique over the Types whose marker is set"""
        updater, dbm = _updater()

        assert updater.build_unique_special_type_index() is True
        (index,) = dbm.create_indexes.call_args.args[2]
        assert index.document == {'key': {module.SPECIAL_TYPE_FIELD: 1}, 'name': module.SPECIAL_TYPE_INDEX,
                                  'unique': True, 'partialFilterExpression': module.MARKER_IS_SET}
        dbm.drop_index.assert_not_called()

    def test_a_unique_index_is_left_alone(self) -> None:
        """Re-run safe"""
        updater, dbm = _updater(index_info={module.SPECIAL_TYPE_INDEX: {module.INDEX_UNIQUE_KEY: True}})

        assert updater.build_unique_special_type_index() is False
        dbm.create_indexes.assert_not_called()

    def test_a_non_unique_index_of_that_name_is_rebuilt(self) -> None:
        """Dropped first"""
        updater, dbm = _updater(index_info={module.SPECIAL_TYPE_INDEX: {}})

        assert updater.build_unique_special_type_index() is True
        dbm.drop_index.assert_called_once_with(module.TYPE_COLLECTION, DATABASE_NAME, module.SPECIAL_TYPE_INDEX)


class TestStartUpdate:
    """Update20261030.start_update"""

    def test_clean_data_gets_the_index_then_the_bump(self) -> None:
        """No duplicate stored"""
        updater, dbm = _updater([_type(1, 'c', CABLE)])
        updater.increase_updater_version = MagicMock()
        order = MagicMock()
        order.attach_mock(dbm.create_indexes, 'create_indexes')
        order.attach_mock(updater.increase_updater_version, 'bump')

        updater.start_update()

        assert order.mock_calls == [order.mock_calls[0], call.bump(CREATION_DATE)]
        assert order.mock_calls[0][0] == 'create_indexes'

    def test_a_duplicate_leaves_the_index_unbuilt_and_still_bumps(self) -> None:
        """Reported once; the startup reconciliation keeps logging until it is resolved"""
        updater, dbm = _updater([_type(3, 'c1', CABLE), _type(9, 'c2', CABLE)])
        updater.increase_updater_version = MagicMock()

        updater.start_update()

        dbm.create_indexes.assert_not_called()
        dbm.get_index_info.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_a_failure_is_wrapped_with_the_exception(self) -> None:
        """The exception itself, not its text; the version is not bumped"""
        updater, dbm = _updater()
        failure = DocumentGetError('read failed')
        dbm.find.side_effect = failure
        updater.increase_updater_version = MagicMock()

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        assert caught.value.args[0] is failure and caught.value.__cause__ is failure
        updater.increase_updater_version.assert_not_called()
