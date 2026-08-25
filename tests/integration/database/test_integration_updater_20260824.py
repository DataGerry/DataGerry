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
Integration tests for cmdb.database.updater.versions.updater_20260824 against a real MongoDB

Reproduces a pre-migration database: the retired 'dg-rackmounting' section template document, one
CmdbType claiming it in global_template_ids, a second CmdbType carrying the inlined section WITHOUT
the claim (the state an old type import leaves behind), CmdbObjects of both holding stored values for
the three fields, and a CmdbReport selecting and filtering on them.

Asserts the migration strips the claim, the layout section, the field definitions and the summary
entry from both types, removes the values from their objects while leaving unrelated fields alone,
strips the field names out of the report and rebuilds its query, deletes the template document, bumps
the persisted updater version, and is idempotent on a second run.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.database.updater.versions.updater_20260824 import (
    RACK_MOUNTING_FIELDS,
    RACK_MOUNTING_TEMPLATE,
    Update20260824,
)
# -------------------------------------------------------------------------------------------------------------------- #

RU_FIELD: str = 'dg-rackmounting-ru'
POSITION_FIELD: str = 'dg-rackmounting-position'
ORIENTATION_FIELD: str = 'dg-rackmounting-orientation'

# A field of the consuming types that has nothing to do with the template and must survive untouched
KEPT_FIELD: str = 'integration-kept-field'
KEPT_SECTION: str = 'integration-kept-section'

# The type that claims the template in global_template_ids (the normal case)
CLAIMING_TYPE_ID: int = 9910
# The type carrying the inlined section with no claim (the old-type-import case)
ORPHAN_TYPE_ID: int = 9911

CLAIMING_OBJECT_ID: int = 9920
ORPHAN_OBJECT_ID: int = 9921

REPORT_ID: int = 9930
TEMPLATE_DOC_ID: int = 9940

TYPE_IDS: list[int] = [CLAIMING_TYPE_ID, ORPHAN_TYPE_ID]
OBJECT_IDS: list[int] = [CLAIMING_OBJECT_ID, ORPHAN_OBJECT_ID]

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'
UPDATER_VERSION: int = 20260824


def _template_doc() -> dict[str, Any]:
    """The retired predefined section template, as shipped before this migration"""
    return {
        'public_id': TEMPLATE_DOC_ID,
        'name': RACK_MOUNTING_TEMPLATE,
        'label': 'Rack mounting',
        'type': SectionType.SECTION.value,
        'is_global': True,
        'predefined': True,
        'fields': [
            {'type': FieldType.TEXT.value, 'name': RU_FIELD, 'label': 'Rack units'},
            {'type': FieldType.TEXT.value, 'name': POSITION_FIELD, 'label': 'Mounting position'},
            {'type': FieldType.SELECT.value, 'name': ORIENTATION_FIELD, 'label': 'Mounting orientation'},
        ],
    }


def _type_doc(public_id: int, with_claim: bool) -> dict[str, Any]:
    """
    Builds a CmdbType consuming the retired section

    'with_claim' decides whether the template is listed in global_template_ids: without it the type
    still carries the inlined section, which is the orphan state the second migration pass exists for
    """
    return {
        'public_id': public_id,
        'name': f'integration-rackmount-type-{public_id}',
        'label': 'Rackmount Type',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'global_template_ids': [RACK_MOUNTING_TEMPLATE] if with_claim else [],
        'fields': [
            {'type': FieldType.TEXT.value, 'name': KEPT_FIELD, 'label': 'Kept'},
            {'type': FieldType.TEXT.value, 'name': RU_FIELD, 'label': 'Rack units'},
            {'type': FieldType.TEXT.value, 'name': POSITION_FIELD, 'label': 'Mounting position'},
            {'type': FieldType.SELECT.value, 'name': ORIENTATION_FIELD, 'label': 'Mounting orientation'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [
                {
                    'type': SectionType.SECTION.value,
                    'name': KEPT_SECTION,
                    'label': 'Kept',
                    'fields': [KEPT_FIELD],
                },
                {
                    'type': SectionType.SECTION.value,
                    'name': RACK_MOUNTING_TEMPLATE,
                    'label': 'Rack mounting',
                    'fields': [RU_FIELD, POSITION_FIELD, ORIENTATION_FIELD],
                },
            ],
            # The position field was a summary field on the assistant's network types
            'summary': {'fields': [KEPT_FIELD, POSITION_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a CmdbObject carrying stored values for the three retired fields plus a kept one"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [
            {'name': KEPT_FIELD, 'value': 'keep me', 'type': FieldType.TEXT.value},
            {'name': RU_FIELD, 'value': '2', 'type': FieldType.TEXT.value},
            {'name': POSITION_FIELD, 'value': '14', 'type': FieldType.TEXT.value},
            {'name': ORIENTATION_FIELD, 'value': 'horizontal', 'type': FieldType.SELECT.value},
        ],
        'multi_data_sections': [],
    }


def _report_doc() -> dict[str, Any]:
    """A CmdbReport of the claiming type that both selects and filters on the retired fields"""
    return {
        'public_id': REPORT_ID,
        'report_category_id': 1,
        'name': 'integration-rackmount-report',
        'type_id': CLAIMING_TYPE_ID,
        'selected_fields': [KEPT_FIELD, RU_FIELD, POSITION_FIELD],
        'conditions': {
            'condition': 'and',
            'rules': [
                {'field': KEPT_FIELD, 'operator': '=', 'value': 'keep me'},
                {'field': POSITION_FIELD, 'operator': '=', 'value': '14'},
            ],
        },
        'report_query': {'data': "{'fields': {'$elemMatch': {'name': 'dg-rackmounting-position'}}}"},
        'predefined': False,
        'mds_mode': 'ROWS',
    }


@pytest.fixture(name='legacy_rackmounting')
def fixture_legacy_rackmounting(database_manager: MongoDatabaseManager, database_name: str):
    """Recreates a pre-migration database carrying the template, its consumers, objects and a report"""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    def _purge() -> None:
        templates.delete_many({'name': RACK_MOUNTING_TEMPLATE})
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        reports.delete_many({'public_id': REPORT_ID})

    _purge()

    templates.insert_one(_template_doc())
    types.insert_many([_type_doc(CLAIMING_TYPE_ID, True), _type_doc(ORPHAN_TYPE_ID, False)])
    objects.insert_many([
        _object_doc(CLAIMING_OBJECT_ID, CLAIMING_TYPE_ID),
        _object_doc(ORPHAN_OBJECT_ID, ORPHAN_TYPE_ID),
    ])
    reports.insert_one(_report_doc())

    yield templates, types, objects, reports

    _purge()

    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260824(database_manager, database_name).start_update()


def _field_names(doc: dict[str, Any]) -> set[str]:
    """The 'name' of every entry in a type's / object's flat field list"""
    return {field['name'] for field in doc['fields']}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    TYPE CLEANUP                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('type_id', [CLAIMING_TYPE_ID, ORPHAN_TYPE_ID])
def test_removes_the_section_from_both_claiming_and_orphaned_types(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str, type_id: int) -> None:
    """The layout section goes, whether or not the type claimed the template"""
    _, types, _, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = types.find_one({'public_id': type_id})
    section_names = {section['name'] for section in stored['render_meta']['sections']}

    assert RACK_MOUNTING_TEMPLATE not in section_names
    assert KEPT_SECTION in section_names


@pytest.mark.parametrize('type_id', [CLAIMING_TYPE_ID, ORPHAN_TYPE_ID])
def test_removes_the_field_definitions_from_both_types(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str, type_id: int) -> None:
    """The three field definitions go and the unrelated one survives"""
    _, types, _, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = types.find_one({'public_id': type_id})

    assert _field_names(stored) == {KEPT_FIELD}


@pytest.mark.parametrize('type_id', [CLAIMING_TYPE_ID, ORPHAN_TYPE_ID])
def test_removes_the_field_from_the_type_summary(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str, type_id: int) -> None:
    """A retired field used as a summary field is dropped from the summary too"""
    _, types, _, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = types.find_one({'public_id': type_id})

    assert stored['render_meta']['summary']['fields'] == [KEPT_FIELD]


def test_drops_the_template_claim(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The claiming type no longer lists the template in global_template_ids"""
    _, types, _, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = types.find_one({'public_id': CLAIMING_TYPE_ID})

    assert RACK_MOUNTING_TEMPLATE not in (stored['global_template_ids'] or [])

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   OBJECT CLEANUP                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('object_id', [CLAIMING_OBJECT_ID, ORPHAN_OBJECT_ID])
def test_removes_the_stored_values_from_the_objects(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> None:
    """Every stored value of the three fields is gone, and the unrelated field keeps its value"""
    _, _, objects, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = objects.find_one({'public_id': object_id})

    assert _field_names(stored) == {KEPT_FIELD}
    assert stored['fields'][0]['value'] == 'keep me'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   REPORT CLEANUP                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_strips_the_fields_from_the_report_selection(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A report no longer selects columns that do not exist any more"""
    _, _, _, reports = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = reports.find_one({'public_id': REPORT_ID})

    assert stored['selected_fields'] == [KEPT_FIELD]


def test_strips_the_fields_from_the_report_conditions(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A condition rule on a removed field is dropped, the unrelated rule survives"""
    _, _, _, reports = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = reports.find_one({'public_id': REPORT_ID})
    rule_fields = {rule['field'] for rule in stored['conditions']['rules']}

    assert rule_fields == {KEPT_FIELD}


def test_rebuilds_the_stored_report_query(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The persisted query is rebuilt, so it no longer references a removed field"""
    _, _, _, reports = legacy_rackmounting

    _run_migration(database_manager, database_name)

    stored = reports.find_one({'public_id': REPORT_ID})

    assert POSITION_FIELD not in stored['report_query']['data']

# -------------------------------------------------------------------------------------------------------------------- #
#                                              TEMPLATE / VERSION / RE-RUN                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def test_deletes_the_template_document(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The predefined template itself is gone, so nothing can attach it again"""
    templates, _, _, _ = legacy_rackmounting

    _run_migration(database_manager, database_name)

    assert templates.find_one({'name': RACK_MOUNTING_TEMPLATE}) is None


@pytest.mark.usefixtures('legacy_rackmounting')
def test_bumps_the_updater_version(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The migration records itself as applied"""
    _run_migration(database_manager, database_name)

    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    stored = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    assert stored is not None
    assert stored['version'] >= UPDATER_VERSION


def test_second_run_is_a_noop(
        legacy_rackmounting, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-running the migration on an already-migrated database changes nothing and does not raise"""
    _, types, objects, reports = legacy_rackmounting

    _run_migration(database_manager, database_name)

    first_types = [types.find_one({'public_id': type_id}) for type_id in TYPE_IDS]
    first_objects = [objects.find_one({'public_id': object_id}) for object_id in OBJECT_IDS]
    first_report = reports.find_one({'public_id': REPORT_ID})

    _run_migration(database_manager, database_name)

    assert [types.find_one({'public_id': type_id}) for type_id in TYPE_IDS] == first_types
    assert [objects.find_one({'public_id': object_id}) for object_id in OBJECT_IDS] == first_objects
    assert reports.find_one({'public_id': REPORT_ID}) == first_report


def test_migration_field_set_matches_the_retired_template(legacy_rackmounting) -> None:
    """The updater's frozen field list is exactly what the retired template contributed"""
    templates, _, _, _ = legacy_rackmounting

    stored = templates.find_one({'name': RACK_MOUNTING_TEMPLATE})

    assert {field['name'] for field in stored['fields']} == set(RACK_MOUNTING_FIELDS)
