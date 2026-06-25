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
Functional tests for IPAM special-type OBJECT feature-gating over HTTP (license feature P15, Step 7)

Creating and deleting an IPAM special-type object (an object whose CmdbType carries a special_type
marker) is blocked with HTTP 403 when IPAM is not licensed - the guard is embedded in the generic
/objects routes (single + bulk delete, insert), so ordinary objects stay fully usable (asserted as
"not 403"). When IPAM is licensed the guard lets the write through. The diff-aware interface-subnet
logic (regular objects) is covered exhaustively by the enforcement unit tests; here we pin the route
wiring and the flat special-type block
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
NAME_FIELD: str = 'dg-name'

SPECIAL_TYPE_ID: int = 47101
NORMAL_TYPE_ID: int = 47102

SPECIAL_OBJECT_ID: int = 47111
NORMAL_OBJECT_ID: int = 47112
NEW_SPECIAL_OBJECT_ID: int = 47113
NEW_NORMAL_OBJECT_ID: int = 47114

TYPE_IDS: list[int] = [SPECIAL_TYPE_ID, NORMAL_TYPE_ID]
OBJECT_IDS: list[int] = [SPECIAL_OBJECT_ID, NORMAL_OBJECT_ID, NEW_SPECIAL_OBJECT_ID, NEW_NORMAL_OBJECT_ID]


def _object_payload(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbObject payload accepted by POST /objects for the given type"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'author_id': 1,
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': 'gated'}],
        'version': '1.0.0',
    }


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(autouse=True)
def _seed_types_and_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an IPAM special type + a normal type with one object each, cleaning up after each test"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SPECIAL_TYPE_ID, 'lic-obj-special', SpecialType.SUBNET),
        make_type_doc(NORMAL_TYPE_ID, 'lic-obj-normal', None),
    ])
    objects.insert_many([
        make_object_doc(SPECIAL_OBJECT_ID, SPECIAL_TYPE_ID, [make_field(NAME_FIELD, 'sn')]),
        make_object_doc(NORMAL_OBJECT_ID, NORMAL_TYPE_ID, [make_field(NAME_FIELD, 'host')]),
    ])

    yield

    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_create_special_type_object_blocked_without_license(rest_api) -> None:
    """Creating an IPAM special-type object is blocked with 403 when IPAM is not licensed"""
    response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(NEW_SPECIAL_OBJECT_ID, SPECIAL_TYPE_ID))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_update_special_type_object_blocked_without_license(rest_api) -> None:
    """Editing an existing IPAM special-type object is blocked with 403 when IPAM is not licensed"""
    payload = _object_payload(SPECIAL_OBJECT_ID, SPECIAL_TYPE_ID)

    assert rest_api.put(f'{OBJECTS_URL}/{SPECIAL_OBJECT_ID}', json=payload).status_code == HTTPStatus.FORBIDDEN


def test_delete_special_type_object_blocked_without_license(rest_api) -> None:
    """Deleting an IPAM special-type object is blocked with 403 when IPAM is not licensed"""
    assert rest_api.delete(f'{OBJECTS_URL}/{SPECIAL_OBJECT_ID}').status_code == HTTPStatus.FORBIDDEN


def test_bulk_delete_blocked_when_a_special_type_object_is_targeted(rest_api) -> None:
    """A bulk delete that includes an IPAM special-type object is blocked with 403 when unlicensed"""
    target_ids = f'{NORMAL_OBJECT_ID},{SPECIAL_OBJECT_ID}'

    assert rest_api.delete(f'{OBJECTS_URL}/delete/{target_ids}').status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          ordinary objects stay usable                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_create_normal_object_allowed_without_license(rest_api) -> None:
    """Creating an ordinary object is NOT gated - it never returns the guard 403"""
    response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(NEW_NORMAL_OBJECT_ID, NORMAL_TYPE_ID))

    assert response.status_code != HTTPStatus.FORBIDDEN


def test_delete_normal_object_allowed_without_license(rest_api) -> None:
    """Deleting an ordinary object is NOT gated - it never returns the guard 403"""
    assert rest_api.delete(f'{OBJECTS_URL}/{NORMAL_OBJECT_ID}').status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_special_type_object_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With IPAM licensed, deleting a special-type object passes the guard (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )

    assert rest_api.delete(f'{OBJECTS_URL}/{SPECIAL_OBJECT_ID}').status_code != HTTPStatus.FORBIDDEN
