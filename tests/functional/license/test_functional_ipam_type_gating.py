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
Functional tests for IPAM special-type TYPE feature-gating over HTTP (license feature P15, Step 6)

Creating, editing and deleting an IPAM special type (a CmdbType carrying a special_type marker:
SUPERNET/SUBNET/VLAN) is blocked with HTTP 403 when IPAM is not licensed. The guard is embedded in
the generic /types routes, so NON-special types stay fully usable - that is asserted too. When IPAM
is licensed (or in cloud/local mode) the guard lets the write through (asserted as "no longer 403")
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'
NAME_FIELD: str = 'dg-name'

SPECIAL_TYPE_ID: int = 47011
NORMAL_TYPE_ID: int = 47012
NEW_SPECIAL_TYPE_ID: int = 47013


def _special_type_payload(public_id: int) -> dict[str, Any]:
    """Builds a CmdbType-shaped payload (accepted by POST/PUT /types) that carries a SpecialType marker"""
    return {
        'public_id': public_id,
        'name': f'lic-special-{public_id}',
        'label': 'Licensed Special Type',
        'author_id': 1,
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        'special_type': SpecialType.SUPERNET.value,
    }


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one IPAM special type and one normal type, cleaning up after each test"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_many([
        make_type_doc(SPECIAL_TYPE_ID, 'lic-ipam-special', SpecialType.SUPERNET),
        make_type_doc(NORMAL_TYPE_ID, 'lic-normal-type', None),
    ])
    yield
    types.delete_many({'public_id': {'$in': [SPECIAL_TYPE_ID, NORMAL_TYPE_ID, NEW_SPECIAL_TYPE_ID]}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_create_special_type_blocked_without_license(rest_api) -> None:
    """Creating an IPAM special type is blocked with 403 when IPAM is not licensed"""
    response = rest_api.post(f'{TYPES_URL}/', json=_special_type_payload(NEW_SPECIAL_TYPE_ID))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_update_special_type_blocked_without_license(rest_api) -> None:
    """Editing an existing IPAM special type is blocked with 403 when IPAM is not licensed"""
    response = rest_api.put(f'{TYPES_URL}/{SPECIAL_TYPE_ID}', json=_special_type_payload(SPECIAL_TYPE_ID))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_delete_special_type_blocked_without_license(rest_api) -> None:
    """Deleting an IPAM special type is blocked with 403 when IPAM is not licensed"""
    assert rest_api.delete(f'{TYPES_URL}/{SPECIAL_TYPE_ID}').status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          normal types stay usable                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_normal_type_allowed_without_license(rest_api) -> None:
    """A non-special type is NOT gated - deleting it without an IPAM license never returns the guard 403"""
    assert rest_api.delete(f'{TYPES_URL}/{NORMAL_TYPE_ID}').status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_special_type_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With IPAM licensed, deleting a special type passes the guard (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )

    assert rest_api.delete(f'{TYPES_URL}/{SPECIAL_TYPE_ID}').status_code != HTTPStatus.FORBIDDEN
