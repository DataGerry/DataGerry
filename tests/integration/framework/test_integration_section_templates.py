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
Integration tests for cmdb.manager.section_templates_manager against a real MongoDB

Seeds a CmdbType that uses a global section template plus a CmdbObject of that type, then drives
the manager's real propagation (handle_section_template_changes / cleanup_global_section_templates)
through TypesManager / ObjectsManager and asserts the persisted type and object documents. Covers
the flat-section diff, the MDS dual-write (a new MDS field lands in both the object's flat fields
and its MDS rows), and the global teardown - including that the teardown also strips the removed
fields out of the type's CmdbReports, which this path has to do itself because it rewrites the type
through types_manager.update_type and so never reaches the type-update route's realignment
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 90100
OBJECT_ID: int = 90101
TEMPLATE_PUBLIC_ID: int = 90102
REPORT_ID: int = 90103

FLAT_TEMPLATE: str = 'it-sectpl-flat'
MDS_TEMPLATE: str = 'it-sectpl-mds'


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> SectionTemplatesManager:
    """Provides a SectionTemplatesManager wired to the test database."""
    return SectionTemplatesManager(database_manager)


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Any:
    """Yields the (types, objects) collections and removes the seeded test documents afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    yield types, objects

    types.delete_many({'public_id': TYPE_ID})
    objects.delete_many({'public_id': OBJECT_ID})


@pytest.fixture(name='reports')
def fixture_reports(database_manager: MongoDatabaseManager, database_name: str) -> Any:
    """Yields the report collection and removes the seeded report afterwards."""
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)

    yield reports

    reports.delete_many({'public_id': REPORT_ID})


def _seed_report(reports: Any) -> None:
    """Seeds a CmdbReport of the type that selects AND filters on a template field ('f-a')."""
    reports.insert_one({
        'public_id': REPORT_ID,
        'report_category_id': 1,
        'name': 'it-sectpl-report',
        'type_id': TYPE_ID,
        'selected_fields': ['dg-name', 'f-a'],
        'conditions': {
            'condition': 'and',
            'rules': [
                {'field': 'dg-name', 'operator': '=', 'value': 'keep'},
                {'field': 'f-a', 'operator': '=', 'value': 'gone'},
            ],
        },
        'report_query': {'data': "{'fields': {'$elemMatch': {'name': 'f-a'}}}"},
        'predefined': False,
        'mds_mode': 'ROWS',
    })


def _seed_flat_type(types: Any, objects: Any) -> None:
    """Seeds a type with a flat global section ['f-a','f-b'] and one object carrying both fields."""
    type_doc = make_type_doc(
        TYPE_ID, 'it-sectpl-type',
        fields=[
            {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
            {'type': 'text', 'name': 'f-a', 'label': 'A'},
            {'type': 'text', 'name': 'f-b', 'label': 'B'},
        ],
        sections=[{'type': 'section', 'name': FLAT_TEMPLATE, 'label': 'Old', 'fields': ['f-a', 'f-b']}],
        global_template_ids=[FLAT_TEMPLATE],
    )
    type_doc['render_meta']['summary']['fields'] = ['f-a', 'f-b']
    types.insert_one(type_doc)

    objects.insert_one(make_object_doc(
        OBJECT_ID, TYPE_ID,
        [make_field('dg-name', 'host'), make_field('f-a', 'a-val'), make_field('f-b', 'b-val')],
    ))


def _field_def(name: str, label: str, value: str | None = None) -> dict[str, Any]:
    """Builds a flat text field definition with an optional default value."""
    field: dict[str, Any] = {'type': 'text', 'name': name, 'label': label}

    if value is not None:
        field['value'] = value

    return field


def _names(field_entries: list[dict[str, Any]]) -> set[str]:
    """Returns the set of field names from a list of stored field entries."""
    return {entry['name'] for entry in field_entries}


# -------------------------------------------------------------------------------------------------------------------- #
#                                 handle_section_template_changes - flat section                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_flat_template_change_propagates_to_type_and_objects(
    manager: SectionTemplatesManager, collections: Any,
) -> None:
    """Adding f-c and removing f-b updates the type schema and the object's flat fields"""
    types, objects = collections
    _seed_flat_type(types, objects)

    current = CmdbSectionTemplate(
        public_id=TEMPLATE_PUBLIC_ID, name=FLAT_TEMPLATE, label='Old', type='section', is_global=True,
        fields=[_field_def('f-a', 'A'), _field_def('f-b', 'B')],
    )
    new_params: dict[str, Any] = {
        'public_id': TEMPLATE_PUBLIC_ID, 'name': FLAT_TEMPLATE, 'label': 'New', 'type': 'section',
        'is_global': True, 'predefined': False,
        'fields': [_field_def('f-a', 'A'), _field_def('f-c', 'C', value='dflt')],
    }

    manager.handle_section_template_changes(new_params, current)

    persisted_type = types.find_one({'public_id': TYPE_ID})
    section = next(s for s in persisted_type['render_meta']['sections'] if s['name'] == FLAT_TEMPLATE)
    assert section['label'] == 'New'
    assert section['fields'] == ['f-a', 'f-c']
    assert _names(persisted_type['fields']) == {'dg-name', 'f-a', 'f-c'}
    assert persisted_type['render_meta']['summary']['fields'] == ['f-a']

    persisted_object = objects.find_one({'public_id': OBJECT_ID})
    assert _names(persisted_object['fields']) == {'dg-name', 'f-a', 'f-c'}
    by_name = {entry['name']: entry['value'] for entry in persisted_object['fields']}
    assert by_name['f-a'] == 'a-val'   # untouched
    assert by_name['f-c'] == 'dflt'    # seeded with the field default


# -------------------------------------------------------------------------------------------------------------------- #
#                                  handle_section_template_changes - MDS section                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_mds_template_change_writes_to_both_flat_fields_and_rows(
    manager: SectionTemplatesManager, collections: Any,
) -> None:
    """A new MDS field lands in the object's flat fields AND in each MDS row (dual-write)"""
    types, objects = collections

    type_doc = make_type_doc(
        TYPE_ID, 'it-sectpl-mds-type',
        fields=[{'type': 'text', 'name': 'dg-name', 'label': 'Name'}, {'type': 'text', 'name': 'm-a', 'label': 'MA'}],
        sections=[{'type': 'multi-data-section', 'name': MDS_TEMPLATE, 'label': 'MDS', 'fields': ['m-a']}],
        global_template_ids=[MDS_TEMPLATE],
    )
    types.insert_one(type_doc)
    objects.insert_one(make_object_doc(
        OBJECT_ID, TYPE_ID,
        [make_field('dg-name', 'host'), make_field('m-a', 'x')],
        mds=[{
            'section_id': MDS_TEMPLATE,
            'values': [{'data': [make_field('m-a', 'x')]}],
        }],
    ))

    current = CmdbSectionTemplate(
        public_id=TEMPLATE_PUBLIC_ID, name=MDS_TEMPLATE, label='MDS', type='multi-data-section', is_global=True,
        fields=[_field_def('m-a', 'MA')],
    )
    new_params: dict[str, Any] = {
        'public_id': TEMPLATE_PUBLIC_ID, 'name': MDS_TEMPLATE, 'label': 'MDS', 'type': 'multi-data-section',
        'is_global': True, 'predefined': False,
        'fields': [_field_def('m-a', 'MA'), _field_def('m-b', 'MB', value='def')],
    }

    manager.handle_section_template_changes(new_params, current)

    persisted_object = objects.find_one({'public_id': OBJECT_ID})
    # flat fields: m-b recorded as the canonical field-list entry
    assert 'm-b' in _names(persisted_object['fields'])
    # MDS row: m-b seeded with its default value
    row_data = persisted_object['multi_data_sections'][0]['values'][0]['data']
    row_by_name = {entry['name']: entry['value'] for entry in row_data}
    assert row_by_name['m-a'] == 'x'
    assert row_by_name['m-b'] == 'def'


# -------------------------------------------------------------------------------------------------------------------- #
#                                       cleanup_global_section_templates                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_global_template_strips_type_and_objects(
    manager: SectionTemplatesManager, collections: Any,
) -> None:
    """Tearing down a global template removes its name/fields/section from the type and objects"""
    types, objects = collections
    _seed_flat_type(types, objects)

    manager.cleanup_global_section_templates(FLAT_TEMPLATE, delete_mode=True)

    persisted_type = types.find_one({'public_id': TYPE_ID})
    assert FLAT_TEMPLATE not in persisted_type['global_template_ids']
    assert _names(persisted_type['fields']) == {'dg-name'}
    assert all(s['name'] != FLAT_TEMPLATE for s in persisted_type['render_meta']['sections'])

    persisted_object = objects.find_one({'public_id': OBJECT_ID})
    assert _names(persisted_object['fields']) == {'dg-name'}


def test_cleanup_global_template_strips_the_types_reports(
    manager: SectionTemplatesManager, collections: Any, reports: Any,
) -> None:
    """The teardown also cleans the reports, which used to be left pointing at deleted fields

    Deleting a global template rewrites the consuming type directly through
    types_manager.update_type, so the type-update route's realignment never runs. Without the
    cleanup here every report of the type kept selecting and filtering on field names that no longer
    existed, with a stale report_query nothing would rebuild.
    """
    types, objects = collections
    _seed_flat_type(types, objects)
    _seed_report(reports)

    manager.cleanup_global_section_templates(FLAT_TEMPLATE, delete_mode=True)

    persisted_report = reports.find_one({'public_id': REPORT_ID})

    assert persisted_report['selected_fields'] == ['dg-name']
    assert [rule['field'] for rule in persisted_report['conditions']['rules']] == ['dg-name']
    assert 'f-a' not in persisted_report['report_query']['data']


def test_cleanup_global_template_leaves_an_unrelated_types_reports_alone(
    manager: SectionTemplatesManager, collections: Any, reports: Any,
) -> None:
    """Only the consuming type's reports are touched - the lookup is scoped by type_id"""
    types, objects = collections
    _seed_flat_type(types, objects)
    _seed_report(reports)
    reports.update_one({'public_id': REPORT_ID}, {'$set': {'type_id': TYPE_ID + 999}})

    manager.cleanup_global_section_templates(FLAT_TEMPLATE, delete_mode=True)

    persisted_report = reports.find_one({'public_id': REPORT_ID})

    assert persisted_report['selected_fields'] == ['dg-name', 'f-a']
