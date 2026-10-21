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
The seed of the type-update alignment tests: one CmdbType and everything that follows it

* the TYPE - a name, a field KEEP and a field DROP in its main section, an MDS section ROWS with MDS_A and MDS_DROP,
  a global section template TEMPLATE (its own section with TEMPLATE_FIELD), label BEFORE_LABEL
* two objects of it, every field filled and one MDS row each
* a location node for each, carrying the type's label
* a report selecting KEEP and DROP and filtering on DROP

``updated_payload`` is the edit the tests save: label AFTER_LABEL and DROP / MDS_DROP removed - or NEW_FIELD / MDS_NEW
added - so every alignment step has something to do. Everything is written straight into the collections
"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 92301
OBJECT_IDS: list[int] = [92311, 92312]
NODE_IDS: list[int] = [92321, 92322]
REPORT_ID: int = 92331
REPORT_CATEGORY_ID: int = 1

NAME_FIELD: str = 'dg_name'
KEEP: str = 'keep'
DROP: str = 'drop'
NEW_FIELD: str = 'new-field'
MDS_SECTION: str = 'rows'
MDS_A: str = 'mds-a'
MDS_DROP: str = 'mds-drop'
MDS_NEW: str = 'mds-new'
TEMPLATE: str = 'dg-align-template'
TEMPLATE_FIELD: str = 'tpl-field'

BEFORE_LABEL: str = 'Alignment Before'
AFTER_LABEL: str = 'Alignment After'
STORED_VALUE: str = 'stored-value'
SEED_AUTHOR_ID: int = 1


def _text(name: str) -> dict[str, Any]:
    """A text field definition."""
    return {'type': FieldType.TEXT.value, 'name': name, 'label': name}


def type_document(with_template: bool = True) -> dict[str, Any]:
    """The stored CmdbType."""
    fields: list[dict[str, Any]] = [_text(name) for name in (NAME_FIELD, KEEP, DROP, MDS_A, MDS_DROP)]
    sections: list[dict[str, Any]] = [
        {'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD, KEEP, DROP]},
        {'type': SectionType.MDS_SECTION.value, 'name': MDS_SECTION, 'label': 'Rows', 'fields': [MDS_A, MDS_DROP]},
    ]

    if with_template:
        fields.append(_text(TEMPLATE_FIELD))
        sections.append({'type': SectionType.SECTION.value, 'name': TEMPLATE, 'label': 'Template',
                         'fields': [TEMPLATE_FIELD]})

    return {
        'public_id': TYPE_ID, 'name': 'align-type', 'label': BEFORE_LABEL, 'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0', 'fields': fields,
        'global_template_ids': [TEMPLATE] if with_template else [],
        'render_meta': {'icon': 'fa-cube', 'sections': sections, 'summary': {'fields': [NAME_FIELD]},
                        'externals': []},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _entry(name: str, value: Any = STORED_VALUE) -> dict[str, Any]:
    """A stored field entry."""
    return {'name': name, 'type': FieldType.TEXT.value, 'value': value}


def _object_document(public_id: int) -> dict[str, Any]:
    """A stored CmdbObject with every field filled and one MDS row."""
    return {
        'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': SEED_AUTHOR_ID, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [_entry(name) for name in (NAME_FIELD, KEEP, DROP, MDS_A, MDS_DROP, TEMPLATE_FIELD)],
        'multi_data_sections': [{'section_id': MDS_SECTION, 'values': [
            {'multi_data_id': 0, 'data': [_entry(MDS_A), _entry(MDS_DROP)]},
        ]}],
    }


def _node_document(node_id: int, object_id: int) -> dict[str, Any]:
    """The location node of an object, carrying the type's label."""
    return {
        'public_id': node_id, 'name': f'node-{object_id}', 'parent': RootLocationDefault.PUBLIC_ID,
        'object_id': object_id, 'type_id': TYPE_ID, 'type_label': BEFORE_LABEL, 'type_icon': 'fa-cube',
        'type_selectable': True,
    }


def _report_document() -> dict[str, Any]:
    """A report selecting KEEP and DROP and filtering on DROP."""
    return {
        'public_id': REPORT_ID, 'report_category_id': REPORT_CATEGORY_ID, 'name': 'align-report', 'type_id': TYPE_ID,
        'selected_fields': [KEEP, DROP],
        'conditions': {'condition': 'and', 'rules': [{'field': DROP, 'operator': '=', 'value': STORED_VALUE}]},
        'report_query': {'data': '{}'}, 'mds_mode': 'ROWS', 'predefined': False,
    }


def seed(database_manager: MongoDatabaseManager, database_name: str, with_template: bool = True) -> None:
    """Writes the type, its objects, their location nodes and the report."""
    purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(type_document(with_template))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many(
        [_object_document(public_id) for public_id in OBJECT_IDS])
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_many(
        [_node_document(node_id, object_id) for node_id, object_id in zip(NODE_IDS, OBJECT_IDS)])
    database_manager.get_collection(CmdbReport.COLLECTION, database_name).insert_one(_report_document())


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many({'public_id': TYPE_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': OBJECT_IDS}})
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': NODE_IDS}})
    database_manager.get_collection(CmdbReport.COLLECTION, database_name).delete_many({'public_id': REPORT_ID})


def updated_payload(stored: dict[str, Any], label: str = AFTER_LABEL, drop_template: bool = False,
                    adding: bool = False) -> dict[str, Any]:
    """
    The edit: a new label and DROP / MDS_DROP removed - or, with ``adding``, NEW_FIELD / MDS_NEW added instead (the type
    guard refuses removing and adding fields in one update while objects exist); optionally the template dropped
    """
    payload: dict[str, Any] = deepcopy(stored)
    payload.pop('_id', None)
    payload['label'] = label

    if adding:
        payload['fields'] += [_text(NEW_FIELD), _text(MDS_NEW)]
    else:
        payload['fields'] = [field for field in payload['fields'] if field['name'] not in (DROP, MDS_DROP)]

    for section in payload['render_meta']['sections']:
        if section['name'] == 'main':
            section['fields'] = [NAME_FIELD, KEEP, NEW_FIELD] if adding else [NAME_FIELD, KEEP]
        elif section['name'] == MDS_SECTION:
            section['fields'] = [MDS_A, MDS_DROP, MDS_NEW] if adding else [MDS_A]

    if drop_template:
        payload['global_template_ids'] = []

    return payload


def stored_type(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """The type as stored."""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name).find_one({'public_id': TYPE_ID})


def object_field_names(database_manager: MongoDatabaseManager, database_name: str) -> list[set[str]]:
    """Per object, the names of its flat fields."""
    return [{field['name'] for field in doc['fields']} for doc in database_manager.get_collection(
        CmdbObject.COLLECTION, database_name).find({'public_id': {'$in': OBJECT_IDS}})]


def mds_row_names(database_manager: MongoDatabaseManager, database_name: str) -> list[set[str]]:
    """Per object, the entry names of its first MDS row (empty when it has no MDS section)."""
    names: list[set[str]] = []

    for doc in database_manager.get_collection(CmdbObject.COLLECTION, database_name).find(
            {'public_id': {'$in': OBJECT_IDS}}):
        sections = doc.get('multi_data_sections') or []
        names.append({entry['name'] for entry in sections[0]['values'][0]['data']} if sections else set())

    return names


def node_labels(database_manager: MongoDatabaseManager, database_name: str) -> set[str]:
    """The type labels the location nodes carry."""
    return {doc['type_label'] for doc in database_manager.get_collection(CmdbLocation.COLLECTION, database_name).find(
        {'public_id': {'$in': NODE_IDS}})}


def report(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """The report as stored."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name).find_one({'public_id': REPORT_ID})
