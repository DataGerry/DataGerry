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
The seed of the reference-section chain tests, in the shape the type builder writes

The builder's section picker offers every section of the target type, reference sections included, so a
reference section can pull in another type's reference section:

* type A - a reference section ``ra`` pulling type B's section ``rb``
* type B - a reference section ``rb`` pulling type C's section ``main``
* type C - a plain ``main`` section with the name field

Each reference section lists its own ``<name>-field`` in its ``fields``, as the builder does. The A object
points at the B object, which points at the C object; C_VALUE is what must reach A's render, two blocks
down. A second A object points at the same B object, for the query counts
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

A_TYPE_ID: int = 89801
B_TYPE_ID: int = 89802
C_TYPE_ID: int = 89803

A_ID: int = 89811
B_ID: int = 89812
C_ID: int = 89813
SECOND_A_ID: int = 89814

NAME_FIELD: str = 'dg_name'
MAIN_SECTION: str = 'main'
A_SECTION: str = 'ra'
B_SECTION: str = 'rb'

A_VALUE: str = 'chain-a-value'
B_VALUE: str = 'chain-b-value'
C_VALUE: str = 'chain-c-value'

ALL_TYPE_IDS: list[int] = [A_TYPE_ID, B_TYPE_ID, C_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [A_ID, B_ID, C_ID, SECOND_A_ID]


def section_field(section_name: str) -> str:
    """The implicit field a reference section stores its reference in."""
    return f'{section_name}-field'


def _type_doc(type_id: int, ref_section: tuple[str, int, str] | None = None) -> dict[str, Any]:
    """A type with a name field in 'main' and, given (name, target type, target section), one reference section."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}]
    sections: list[dict[str, Any]] = [
        {'type': SectionType.SECTION.value, 'name': MAIN_SECTION, 'label': 'Main', 'fields': [NAME_FIELD]},
    ]

    if ref_section is not None:
        name, target_type_id, target_section = ref_section
        fields.append({'type': FieldType.REF_SECTION.value, 'name': section_field(name), 'label': name,
                       'ref_types': [target_type_id]})
        sections.append({
            'type': SectionType.REF_SECTION.value, 'name': name, 'label': name, 'fields': [section_field(name)],
            'reference': {'type_id': target_type_id, 'section_name': target_section, 'selected_fields': []},
        })

    return make_type_doc(type_id, f'chain-{type_id}', fields=fields, sections=sections)


def _object_doc(public_id: int, type_id: int, value: str, section: str | None = None,
                target: int | None = None) -> dict[str, Any]:
    """An object named `value`, whose `section` field points at `target`."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': value}]

    if section is not None:
        fields.append({'type': FieldType.REF_SECTION.value, 'name': section_field(section), 'value': target})

    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': fields, 'multi_data_sections': [],
    }


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes the three types and the four objects."""
    purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_many([
        _type_doc(A_TYPE_ID, (A_SECTION, B_TYPE_ID, B_SECTION)),
        _type_doc(B_TYPE_ID, (B_SECTION, C_TYPE_ID, MAIN_SECTION)),
        _type_doc(C_TYPE_ID),
    ])
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        _object_doc(A_ID, A_TYPE_ID, A_VALUE, A_SECTION, B_ID),
        _object_doc(SECOND_A_ID, A_TYPE_ID, A_VALUE, A_SECTION, B_ID),
        _object_doc(B_ID, B_TYPE_ID, B_VALUE, B_SECTION, C_ID),
        _object_doc(C_ID, C_TYPE_ID, C_VALUE),
    ])


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_OBJECT_IDS}})


def nested_block(rendered: dict[str, Any]) -> dict[str, Any]:
    """The block B's pulled-in 'rb-field' carries inside A's rendered 'ra' section."""
    ra_field: dict[str, Any] = next(field for field in rendered['fields'] if field['name'] == section_field(A_SECTION))
    rb_field: dict[str, Any] = next(field for field in ra_field['references']['fields']
                                    if field['name'] == section_field(B_SECTION))

    return rb_field['references']
