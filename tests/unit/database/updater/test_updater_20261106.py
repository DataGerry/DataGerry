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
Unit tests for cmdb.database.updater.versions.updater_20261106

The migration sets every object field entry's type to the one its field declares, keeping the values. Its run
against a real database is its own integration test; this module owns the frozen literals, the statement it builds
per type, the version bump and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from pymongo import UpdateMany

from cmdb.database.updater.versions import updater_20261106 as module
from cmdb.database.updater.versions.updater_20261106 import Update20261106, build_stamp_operation
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261106
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'objects gone'
TYPE_DOCUMENT: dict[str, Any] = {'public_id': 7, 'fields': [{'name': 'status', 'type': 'select'}, {'name': 'n'}]}


def _updater(types: list[dict[str, Any]]) -> tuple[Update20261106, MagicMock]:
    """The migration over a mocked database manager whose type read answers `types`"""
    dbm = MagicMock()
    dbm.find.return_value = iter(types)
    updater = Update20261106(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.TYPES_COLLECTION, CmdbType.COLLECTION),
    (module.OBJECTS_COLLECTION, CmdbObject.COLLECTION),
    (module.TYPE_FIELDS_FIELD, TypeSchemaKey.FIELDS.value),
    (module.OBJECT_TYPE_ID_FIELD, CmdbObjectKey.TYPE_ID.value),
    (module.OBJECT_FIELDS_FIELD, CmdbObjectKey.FIELDS.value),
    (module.OBJECT_MDS_FIELD, CmdbObjectKey.MULTI_DATA_SECTIONS.value),
    (module.MDS_VALUES_FIELD, CmdbObjectMdsKey.VALUES.value),
    (module.MDS_ROW_DATA_FIELD, CmdbObjectMdsRowKey.DATA.value),
    (module.ENTRY_NAME_KEY, CmdbObjectFieldKey.NAME.value),
    (module.ENTRY_TYPE_KEY, CmdbObjectFieldKey.TYPE.value),
    (module.FALLBACK_FIELD_TYPE, FieldType.TEXT.value),
], ids=['types', 'objects', 'type-fields', 'type-id', 'fields', 'mds', 'values', 'data', 'name', 'type', 'fallback'])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The literals were frozen from the code's own"""
    assert frozen == live


class TestBuildStampOperation:
    """One update per type: its objects, flat entries and MDS rows, the type only"""

    def test_scoped_to_the_objects_of_the_type(self) -> None:
        """An UpdateMany on type_id with one $set stage over both arrays"""
        operation = build_stamp_operation(TYPE_DOCUMENT)

        assert isinstance(operation, UpdateMany)
        assert operation._filter == {'type_id': 7}  # pylint: disable=protected-access
        (stage,) = operation._doc  # pylint: disable=protected-access
        assert set(stage['$set']) == {'fields', 'multi_data_sections'}

    def test_only_the_type_is_set_never_the_value(self) -> None:
        """Stamp only: a value is kept whatever it is"""
        rendered = repr(build_stamp_operation(TYPE_DOCUMENT)._doc)  # pylint: disable=protected-access

        assert "'value'" not in rendered
        assert "{'$literal': ['select', 'text']}" in rendered

    @pytest.mark.parametrize('type_document', [
        pytest.param({'public_id': 7, 'fields': []}, id='no fields'),
        pytest.param({'public_id': 7}, id='no list'),
        pytest.param({'public_id': 7, 'fields': ['status', {'label': 'x'}, {'name': 3}]}, id='no named field'),
    ])
    def test_a_type_declaring_no_usable_field_builds_nothing(self, type_document: dict[str, Any]) -> None:
        """Nothing to stamp, no statement"""
        assert build_stamp_operation(type_document) is None


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater([])

    assert updater.creation_date() == CREATION_DATE
    assert 'type' in updater.description()


def test_one_bulk_write_for_every_type_then_the_version() -> None:
    """A type without a usable public_id or field is skipped; the rest go in one bulk write"""
    updater, dbm = _updater([TYPE_DOCUMENT, {'public_id': 'x', 'fields': [{'name': 'a'}]}, {'public_id': 8}])

    updater.start_update()

    collection, database, operations = dbm.bulk_write.call_args.args
    assert (collection, database, len(operations)) == (module.OBJECTS_COLLECTION, DATABASE_NAME, 1)
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_no_type_writes_nothing_and_still_bumps() -> None:
    """An empty database: no write, the version moves"""
    updater, dbm = _updater([])

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_update_is_the_updater_exception_carrying_it() -> None:
    """The failure tail wraps the exception itself, and the version does not move"""
    updater, dbm = _updater([TYPE_DOCUMENT])
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
