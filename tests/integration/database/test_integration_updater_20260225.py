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
Integration tests for cmdb.database.updater.versions.updater_20260225 against a real MongoDB

The unit tests pin every query with mocked managers; these run the whole migration against real
collections seeded with a pre-migration baseline: three CmdbTypes (a plain one, one carrying a
multi-data-section, one whose schema declares no field at all) and objects holding untyped entries,
already-typed entries, entries stored with a null / empty type, entries the schema no longer declares,
and - the shape that used to abort the whole migration - a multi-data-section without a 'values' array
plus a row without a 'data' array.

Covered end to end: the backfill writes the schema's field type onto absent / null / empty entries in
both the top-level list and the multi-data rows, an already-typed entry keeps its stored type, entries
the schema no longer declares are pulled from both places, malformed sections and rows are skipped
instead of failing the run, objects of a type declaring no field name are left untouched, the persisted
updater version is bumped, and a **second run changes nothing**.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.database.updater.versions.updater_20260225 import (
    FIELD_NAME_KEY,
    FIELD_TYPE_KEY,
    MDS_SECTION_TYPE,
    Update20260225,
)
# -------------------------------------------------------------------------------------------------------------------- #

PLAIN_TYPE_ID: int = 9241
MDS_TYPE_ID: int = 9242
FIELDLESS_TYPE_ID: int = 9243
TYPE_IDS: list[int] = [PLAIN_TYPE_ID, MDS_TYPE_ID, FIELDLESS_TYPE_ID]

PLAIN_OBJECT_ID: int = 9251
MDS_OBJECT_ID: int = 9252
MALFORMED_MDS_OBJECT_ID: int = 9253
FIELDLESS_OBJECT_ID: int = 9254
OBJECT_IDS: list[int] = [PLAIN_OBJECT_ID, MDS_OBJECT_ID, MALFORMED_MDS_OBJECT_ID, FIELDLESS_OBJECT_ID]

UPDATER_VERSION: int = 20260225
UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'

NAME_FIELD: str = 'dg-name'
REF_FIELD: str = 'dg-owner'
ORPHAN_FIELD: str = 'dg-removed-from-the-schema'
MDS_SECTION_ID: str = 'it-mds-section'


def _field(name: str, value: Any, field_type: Any = None) -> dict[str, Any]:
    """Builds one stored field entry; the type key is omitted when no type is given."""
    entry: dict[str, Any] = {FIELD_NAME_KEY: name, 'value': value}

    if field_type is not None:
        entry[FIELD_TYPE_KEY] = field_type

    return entry


def _type_doc(
    public_id: int, name: str, fields: list[dict[str, Any]], sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Builds a minimal active CmdbType document."""
    return {
        'public_id': public_id,
        'name': name,
        'label': name,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'sections': sections, 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]], mds: list[dict[str, Any]] | None = None):
    """Builds a minimal active CmdbObject document, optionally carrying multi_data_sections."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': fields,
    }

    if mds is not None:
        doc['multi_data_sections'] = mds

    return doc


@pytest.fixture(scope='module', autouse=True, name='seeded_baseline')
def fixture_seeded_baseline(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the pre-migration baseline (types and objects), cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    previous_updater_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    plain_fields = [
        {FIELD_TYPE_KEY: 'text', FIELD_NAME_KEY: NAME_FIELD, 'label': 'Name'},
        {FIELD_TYPE_KEY: 'ref', FIELD_NAME_KEY: REF_FIELD, 'label': 'Owner'},
    ]
    plain_section = {'type': 'section', 'name': 'information', 'label': 'Information',
                     'fields': [NAME_FIELD, REF_FIELD]}
    mds_section = {'type': MDS_SECTION_TYPE, 'name': MDS_SECTION_ID, 'label': 'Rows',
                   'fields': [NAME_FIELD, REF_FIELD]}

    types.insert_many([
        _type_doc(PLAIN_TYPE_ID, 'it-backfill-plain', plain_fields, [plain_section]),
        _type_doc(MDS_TYPE_ID, 'it-backfill-mds', plain_fields, [plain_section, mds_section]),
        _type_doc(FIELDLESS_TYPE_ID, 'it-backfill-fieldless', [], [plain_section]),
    ])

    objects.insert_many([
        # untyped / null / empty / already-typed / undeclared, all in one top-level list
        _object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID, [
            _field(NAME_FIELD, 'host-a'),
            {FIELD_NAME_KEY: REF_FIELD, 'value': 7, FIELD_TYPE_KEY: None},
            _field(ORPHAN_FIELD, 'left over'),
        ]),
        # the same shapes inside a multi-data-section row
        _object_doc(MDS_OBJECT_ID, MDS_TYPE_ID, [
            _field(NAME_FIELD, 'host-b'),
            _field(REF_FIELD, 9, 'ref'),
        ], mds=[{
            'section_id': MDS_SECTION_ID,
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [
                    _field(NAME_FIELD, 'row-1'),
                    {FIELD_NAME_KEY: REF_FIELD, 'value': 11, FIELD_TYPE_KEY: ''},
                    _field(ORPHAN_FIELD, 'row leftover'),
                ]},
                {'multi_data_id': 2, 'data': [_field(NAME_FIELD, 'row-2', 'text')]},
            ],
        }]),
        # a section without 'values' and a row without 'data' - used to abort the whole migration
        _object_doc(MALFORMED_MDS_OBJECT_ID, MDS_TYPE_ID, [_field(NAME_FIELD, 'host-c')], mds=[
            {'section_id': MDS_SECTION_ID, 'values': [
                {'multi_data_id': 1, 'data': [_field(NAME_FIELD, 'row-ok')]},
                {'multi_data_id': 2},
            ]},
            {'section_id': 'it-section-without-values'},
        ]),
        # a type whose schema declares no field name at all: nothing may be stripped
        _object_doc(FIELDLESS_OBJECT_ID, FIELDLESS_TYPE_ID, [_field(NAME_FIELD, 'host-d')]),
    ])

    yield

    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    if previous_updater_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_updater_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


@pytest.fixture(scope='module', autouse=True, name='run_updater')
def fixture_run_updater(  # pylint: disable=unused-argument
    seeded_baseline, database_manager: MongoDatabaseManager, database_name: str,
):
    """Runs the migration once against the seeded baseline; depends on it purely for ordering."""
    Update20260225(database_manager, database_name).start_update()
    yield


@pytest.fixture(name='objects_collection')
def fixture_objects_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbObject collection."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _fields_by_name(objects_collection, public_id: int) -> dict[str, dict[str, Any]]:
    """Reads one object's top-level field entries, keyed by field name."""
    doc = objects_collection.find_one({'public_id': public_id}, {'_id': 0, 'fields': 1})

    return {entry[FIELD_NAME_KEY]: entry for entry in doc['fields']}


def _mds_rows(objects_collection, public_id: int) -> list[dict[str, Any]]:
    """Reads one object's multi-data-section rows of the seeded section."""
    doc = objects_collection.find_one({'public_id': public_id}, {'_id': 0, 'multi_data_sections': 1})

    return doc['multi_data_sections'][0]['values']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     backfill                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_untyped_top_level_field_gets_the_schema_type(objects_collection) -> None:
    """An entry stored without a 'type' key is filled from the type schema"""
    assert _fields_by_name(objects_collection, PLAIN_OBJECT_ID)[NAME_FIELD][FIELD_TYPE_KEY] == 'text'


def test_null_type_is_treated_as_untyped(objects_collection) -> None:
    """An entry stored with type=None is filled, not skipped as 'already set'"""
    assert _fields_by_name(objects_collection, PLAIN_OBJECT_ID)[REF_FIELD][FIELD_TYPE_KEY] == 'ref'


def test_empty_type_inside_a_multi_data_row_is_treated_as_untyped(objects_collection) -> None:
    """An MDS entry stored with type='' is filled from the type schema"""
    row = _mds_rows(objects_collection, MDS_OBJECT_ID)[0]
    entries = {entry[FIELD_NAME_KEY]: entry for entry in row['data']}

    assert entries[REF_FIELD][FIELD_TYPE_KEY] == 'ref'


def test_untyped_multi_data_row_field_gets_the_schema_type(objects_collection) -> None:
    """An MDS entry stored without a 'type' key is filled from the type schema"""
    row = _mds_rows(objects_collection, MDS_OBJECT_ID)[0]
    entries = {entry[FIELD_NAME_KEY]: entry for entry in row['data']}

    assert entries[NAME_FIELD][FIELD_TYPE_KEY] == 'text'


def test_an_already_typed_entry_keeps_its_stored_type(objects_collection) -> None:
    """A non-empty stored type is never rewritten, so a later type change is not undone"""
    second_row = _mds_rows(objects_collection, MDS_OBJECT_ID)[1]

    assert second_row['data'][0][FIELD_TYPE_KEY] == 'text'
    assert _fields_by_name(objects_collection, MDS_OBJECT_ID)[REF_FIELD][FIELD_TYPE_KEY] == 'ref'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      strip                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_undeclared_top_level_field_is_stripped(objects_collection) -> None:
    """A field the type schema no longer declares is removed from the object"""
    assert ORPHAN_FIELD not in _fields_by_name(objects_collection, PLAIN_OBJECT_ID)


def test_undeclared_multi_data_row_field_is_stripped(objects_collection) -> None:
    """A field the type schema no longer declares is removed from every MDS row too"""
    row = _mds_rows(objects_collection, MDS_OBJECT_ID)[0]

    assert [entry[FIELD_NAME_KEY] for entry in row['data']] == [NAME_FIELD, REF_FIELD]


def test_declared_fields_survive_the_strip(objects_collection) -> None:
    """Only the undeclared entry is pulled; the declared ones stay"""
    assert set(_fields_by_name(objects_collection, PLAIN_OBJECT_ID)) == {NAME_FIELD, REF_FIELD}


def test_a_type_declaring_no_field_name_strips_nothing(objects_collection) -> None:
    """An empty name set would empty every object, so such a type is skipped entirely"""
    entries = _fields_by_name(objects_collection, FIELDLESS_OBJECT_ID)

    assert set(entries) == {NAME_FIELD}
    assert FIELD_TYPE_KEY not in entries[NAME_FIELD]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              malformed shapes survive                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_section_without_values_does_not_abort_the_migration(objects_collection) -> None:
    """The guarded traversal skips a section carrying no 'values' array instead of failing the run"""
    doc = objects_collection.find_one({'public_id': MALFORMED_MDS_OBJECT_ID}, {'_id': 0, 'multi_data_sections': 1})
    broken = doc['multi_data_sections'][1]

    assert broken == {'section_id': 'it-section-without-values'}


def test_a_row_without_data_does_not_abort_the_migration(objects_collection) -> None:
    """A row carrying no 'data' array is skipped, and its healthy sibling is still migrated"""
    rows = _mds_rows(objects_collection, MALFORMED_MDS_OBJECT_ID)

    assert rows[1] == {'multi_data_id': 2}
    assert rows[0]['data'][0][FIELD_TYPE_KEY] == 'text'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              version bump + re-run                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_updater_version_is_persisted(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The migration bumps the stored updater version as its last step"""
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == UPDATER_VERSION


def test_a_second_run_changes_nothing(
    database_manager: MongoDatabaseManager, database_name: str, objects_collection,
) -> None:
    """Re-run safety: re-entering the migration over its own output is a no-op"""
    before = list(objects_collection.find({'public_id': {'$in': OBJECT_IDS}}, {'_id': 0}).sort('public_id', 1))

    Update20260225(database_manager, database_name).start_update()

    after = list(objects_collection.find({'public_id': {'$in': OBJECT_IDS}}, {'_id': 0}).sort('public_id', 1))
    assert after == before
