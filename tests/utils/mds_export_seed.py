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
The seed of the multi-data-section export tests: one type with a regular field and an MDS section, one object

The object's flat ``fields`` carries its MDS fields too - as the frontend saves an object - with values NO row holds
(FLAT_PORT, FLAT_SPEED), so a test can tell the flat copy from the row values wherever it shows up. Everything is
written straight into the collections
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

TYPE_ID: int = 98201
OBJECT_ID: int = 98211
TYPE_LABEL: str = 'mds-export'

NAME_FIELD: str = 'dg-name'
SECTION_ID: str = 'ports'
PORT_FIELD: str = 'port'
SPEED_FIELD: str = 'speed'
MDS_FIELDS: list[str] = [PORT_FIELD, SPEED_FIELD]

NAME_VALUE: str = 'mds-host'
FLAT_PORT: str = 'flat-port-value'
FLAT_SPEED: str = 'flat-speed-value'
#: The rows, as (port, speed) pairs
ROWS: list[tuple[str, str]] = [('eth0', '1G'), ('eth1', '10G')]


def _text(name: str) -> dict[str, Any]:
    """A text field definition"""
    return {'type': FieldType.TEXT.value, 'name': name, 'label': name}


def stored_flat_fields() -> list[dict[str, Any]]:
    """The object's flat field entries, MDS fields included"""
    return [
        {'name': NAME_FIELD, 'value': NAME_VALUE},
        {'name': PORT_FIELD, 'value': FLAT_PORT},
        {'name': SPEED_FIELD, 'value': FLAT_SPEED},
    ]


def stored_rows() -> list[list[tuple[str, str]]]:
    """The object's MDS rows, as (name, value) pairs per row"""
    return [[(PORT_FIELD, port), (SPEED_FIELD, speed)] for port, speed in ROWS]


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes the type and the object"""
    purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(make_type_doc(
        TYPE_ID, TYPE_LABEL,
        fields=[_text(NAME_FIELD), _text(PORT_FIELD), _text(SPEED_FIELD)],
        sections=[
            {'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]},
            {'type': SectionType.MDS_SECTION.value, 'name': SECTION_ID, 'label': 'Ports', 'fields': MDS_FIELDS},
        ],
    ))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one({
        'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': stored_flat_fields(),
        'multi_data_sections': [{'section_id': SECTION_ID, 'highest_id': len(ROWS), 'values': [
            {'multi_data_id': index, 'data': [{'name': name, 'value': value} for name, value in row]}
            for index, row in enumerate(stored_rows(), start=1)
        ]}],
    })


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes the type and every object of it - the seeded one and any an import created"""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many({'public_id': TYPE_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'type_id': TYPE_ID})
