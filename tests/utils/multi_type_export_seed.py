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
Seed documents for an object export whose selection spans two types

A Server type and a Router type sharing one field name, which each type declares in a different position,
plus one object of each. Shared by the functional and the integration tests of the multi-type export
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 47601
ROUTER_TYPE_ID: int = 47602
SERVER_OBJECT_ID: int = 47611
ROUTER_OBJECT_ID: int = 47612
SEEDED_TYPE_IDS: list[int] = [SERVER_TYPE_ID, ROUTER_TYPE_ID]
SEEDED_OBJECT_IDS: list[int] = [SERVER_OBJECT_ID, ROUTER_OBJECT_ID]

SERVER_LABEL: str = 'Export Server'
ROUTER_LABEL: str = 'Export Router'

SHARED_FIELD: str = 'name'
SERVER_FIELD: str = 'rack-unit'
ROUTER_FIELD: str = 'ip'

SERVER_FIELDS: list[str] = [SHARED_FIELD, SERVER_FIELD]
ROUTER_FIELDS: list[str] = [ROUTER_FIELD, SHARED_FIELD]

SERVER_VALUES: dict[str, str] = {SHARED_FIELD: 'srv-1', SERVER_FIELD: '12'}
ROUTER_VALUES: dict[str, str] = {ROUTER_FIELD: '10.0.0.1', SHARED_FIELD: 'rtr-1'}


def type_doc(type_id: int, label: str, field_names: list[str]) -> dict[str, Any]:
    """
    An active CmdbType with one text field per name, all in one section

    Args:
        type_id (int): The type's public_id
        label (str): The type's label
        field_names (list[str]): The type's field names, in its own order

    Returns:
        dict[str, Any]: The stored type document
    """
    return {
        'public_id': type_id,
        'name': f'multi-export-{type_id}',
        'label': label,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': name, 'label': name} for name in field_names],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': field_names}],
            'summary': {'fields': field_names[:1]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def object_doc(public_id: int, type_id: int, values: dict[str, str]) -> dict[str, Any]:
    """
    A CmdbObject of the given type holding the given text values

    Args:
        public_id (int): The object's public_id
        type_id (int): The object's type
        values (dict[str, str]): The text values by field name

    Returns:
        dict[str, Any]: The stored object document
    """
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': name, 'value': value} for name, value in values.items()],
    }


def purge(dbm: MongoDatabaseManager, database_name: str) -> None:
    """
    Removes every seeded type and object

    Args:
        dbm (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    dbm.get_collection(CmdbType.COLLECTION, database_name).delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})
    dbm.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'public_id': {'$in': SEEDED_OBJECT_IDS}})


def seed(dbm: MongoDatabaseManager, database_name: str, router_label: str = ROUTER_LABEL) -> None:
    """
    Seeds the Server and the Router type with one object each

    Args:
        dbm (MongoDatabaseManager): The test database manager
        database_name (str): The test database
        router_label (str): The Router type's label - the Server's, to have two types share one
    """
    dbm.get_collection(CmdbType.COLLECTION, database_name).insert_many([
        type_doc(SERVER_TYPE_ID, SERVER_LABEL, SERVER_FIELDS),
        type_doc(ROUTER_TYPE_ID, router_label, ROUTER_FIELDS),
    ])
    dbm.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        object_doc(SERVER_OBJECT_ID, SERVER_TYPE_ID, SERVER_VALUES),
        object_doc(ROUTER_OBJECT_ID, ROUTER_TYPE_ID, ROUTER_VALUES),
    ])
