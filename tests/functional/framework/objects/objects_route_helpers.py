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
Shared seed vocabulary and document builders for the ``/objects`` functional tests

Every module in this package seeds CmdbType / CmdbObject documents directly into the collections
rather than through the routes, so these builders are the one place the baseline shapes are
defined. The ids are here too, in one block, because they have to stay distinct **across** the
modules: each test cleans up after itself, but two modules picking the same public_id would make
the order they run in matter.

Builders return plain dicts ready for ``insert_one``. Anything only one module needs stays in that
module
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

LOCATIONS_ROUTE_URL: str = '/locations'

TYPE_ID: int = 9401

TYPE_NAME: str = 'route-smoke-type'

NAME_FIELD: str = 'name-field'

OBJECT_ID_FOR_CREATE: int = 9411

OBJECT_ID_FOR_GET: int = 9412

OBJECT_ID_FOR_UPDATE: int = 9413

OBJECT_ID_FOR_DELETE: int = 9414

OBJECT_ID_FOR_PATCH: int = 9415

OBJECT_ID_FOR_VALUES: int = 9416

BULK_OBJECT_IDS: list[int] = [9421, 9422, 9423]

MISSING_OBJECT_ID: int = 9499

ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_DELETE,
    OBJECT_ID_FOR_PATCH,
    OBJECT_ID_FOR_VALUES,
] + BULK_OBJECT_IDS

ORIGINAL_VALUE: str = 'original'

UPDATED_VALUE: str = 'updated'

BULK_UPDATED_VALUE: str = 'bulk-updated'

SEED_VERSION: str = '1.0.0'

UPDATE_VERSION: str = '1.0.1'

SEED_AUTHOR_ID: int = 1


# public_id of the authenticated user behind the rest_api fixture (full_access_user); the update
# pipeline stamps this as the object's editor_id
REQUEST_USER_ID: int = 1


def type_doc() -> dict[str, Any]:
    """Builds an active CmdbType doc whose presence the route insert/update paths require.

    The section referencing NAME_FIELD is required: the PUT route reconstructs the
    object's field list from the render result, which itself walks the type's
    render_meta.sections — fields not surfaced by a section are silently dropped.
    """
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Route Smoke Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def object_payload(public_id: int, value: str) -> dict[str, Any]:
    """Builds a CmdbObject-shaped payload acceptable to POST /objects/ and PUT /objects/<id>."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}],
    }


def object_doc(public_id: int, value: str) -> dict[str, Any]:
    """Builds a complete CmdbObject doc for direct DB insertion (bypasses route validation)."""
    payload = object_payload(public_id, value)
    payload['creation_time'] = datetime.now(timezone.utc)
    return payload


def drop_object(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbObject doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_one({'public_id': public_id})


def insert_object_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int, value: str) -> None:
    """Inserts a CmdbObject doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(object_doc(public_id, value))


ROOT_LOCATION_ID: int = 1  # the synthetic location-tree root; a top-level node's parent


# A type whose ref field lives inside a multi-data section, to exercise the MDS reference path
MDS_REF_TYPE_ID: int = 9403

MDS_REF_FIELD: str = 'mds-ref'


def mds_ref_type_doc() -> dict[str, Any]:
    """Builds a CmdbType whose ref field (pointing at TYPE_ID) is part of a multi-data section."""
    return {
        'public_id': MDS_REF_TYPE_ID,
        'name': f'mds-ref-type-{MDS_REF_TYPE_ID}',
        'label': 'MDS Ref Type',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        'fields': [{'type': 'ref', 'name': MDS_REF_FIELD, 'label': 'MDS Ref', 'ref_types': [TYPE_ID]}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{
                'type': 'multi-data-section', 'name': 'mds-section', 'label': 'MDS', 'fields': [MDS_REF_FIELD],
            }],
            'summary': {'fields': []},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
    }


def mds_referencing_object_doc(public_id: int, target_id: int) -> dict[str, Any]:
    """Builds a CmdbObject whose multi-data-section row holds a ref field pointing at target_id."""
    return {
        'public_id': public_id,
        'type_id': MDS_REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [],
        'multi_data_sections': [{
            'section_id': 'mds-section',
            'values': [{
                'multi_data_id': 1,
                'data': [{'type': 'ref', 'name': MDS_REF_FIELD, 'value': target_id}],
            }],
        }],
        'creation_time': datetime.now(timezone.utc),
    }
