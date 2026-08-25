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
Functional tests for Rack View feature-gating over HTTP

The Rack View is gated behind ``LicenseFeature.IPAM`` as an INTERIM decision: a Rack is not an IPAM
type (``SpecialType.get_ipam_types`` still excludes it) and the feature is expected to get a
``LicenseFeature`` of its own later. Until then the gate covers four surfaces, all asserted here:

* the dedicated ``/racks`` surface - both blueprints, reads included, blocked by a blueprint guard
  before the view runs
* creating / editing a RACK CmdbType
* writing / deleting a Rack CmdbObject
* the start assistant's ``rack-profile``, which bypasses every route guard because it writes through
  the managers directly - covered in tests/unit/.../test_special_helper.py, at the ``feature_locked``
  seam: ``request_has_feature`` caches per request on ``flask.g``, which leaks across the
  session-scoped app context, so that half cannot be asserted reliably from here

The ``/racks`` cases are also the regression guard for a trap in the wiring: ``gate_blueprint``
installs a ``before_request`` hook and Flask runs a blueprint's deferred setup at registration time,
so gating a blueprint that is *already registered* silently does nothing. These tests fail if the
rack blueprints are ever registered before the gate loop again.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

RACK_TYPE_ID: int = 9750
RACK_OBJECT_ID: int = 9751

# One representative route per gated rack blueprint: the mounts/overview surface and the picker
RACK_OVERVIEW_URL: str = f'/racks/{RACK_OBJECT_ID}/overview'
RACK_MOUNTS_URL: str = f'/racks/{RACK_OBJECT_ID}/mounts/'
RACK_ASSIGNABLE_URL: str = f'/racks/{RACK_OBJECT_ID}/assignable_objects/'
RACK_MOUNT_OF_OBJECT_URL: str = f'/racks/mounts/object/{RACK_OBJECT_ID}'

GATED_READ_URLS: list[str] = [
    RACK_OVERVIEW_URL,
    RACK_MOUNTS_URL,
    RACK_ASSIGNABLE_URL,
    RACK_MOUNT_OF_OBJECT_URL,
]

TYPES_URL: str = '/types'
OBJECTS_URL: str = '/objects'


def _rack_type_doc() -> dict[str, Any]:
    """A RACK SpecialType document, enough for the object write path to resolve the marker."""
    return {
        'public_id': RACK_TYPE_ID,
        'name': 'gating-rack',
        'label': 'Gating Rack',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [
            {'type': FieldType.TEXT.value, 'name': 'dg-rack-name', 'label': 'Rackname'},
            {'type': FieldType.NUMBER.value, 'name': 'dg-rack-height', 'label': 'Height'},
        ],
        'render_meta': {
            'icon': 'fas fa-th-large',
            'externals': [],
            'sections': [{
                'type': SectionType.SECTION.value,
                'name': 'dg-rack-information',
                'label': 'Information',
                'fields': ['dg-rack-name', 'dg-rack-height'],
            }],
            'summary': {'fields': ['dg-rack-name']},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _rack_object_payload() -> dict[str, Any]:
    """A Rack CmdbObject write payload."""
    return {
        'type_id': RACK_TYPE_ID,
        'active': True,
        'fields': [
            {'name': 'dg-rack-name', 'value': 'gated-rack'},
            {'name': 'dg-rack-height', 'value': 42},
        ],
    }


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(name='seeded_rack')
def fixture_seeded_rack(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a RACK type and a Rack object directly, so the gate is what blocks - not a missing target."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.delete_many({'public_id': RACK_TYPE_ID})
    objects.delete_many({'public_id': RACK_OBJECT_ID})

    types.insert_one(_rack_type_doc())
    objects.insert_one({
        'public_id': RACK_OBJECT_ID,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [
            {'name': 'dg-rack-name', 'value': 'gated-rack', 'type': FieldType.TEXT.value},
            {'name': 'dg-rack-height', 'value': 42, 'type': FieldType.NUMBER.value},
        ],
        'multi_data_sections': [],
    })

    yield

    types.delete_many({'public_id': RACK_TYPE_ID})
    objects.delete_many({'public_id': RACK_OBJECT_ID})


def _license_ipam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlocks IPAM (and only IPAM) for the duration of a test."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

# -------------------------------------------------------------------------------------------------------------------- #
#                                       the /racks surface, blocked unlicensed                                         #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('url', GATED_READ_URLS)
@pytest.mark.usefixtures('seeded_rack')
def test_rack_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every /racks read is blocked with 403 when IPAM is not licensed - reads lock too"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_rack')
def test_rack_mount_write_blocked_without_license(rest_api) -> None:
    """Creating a mount is blocked before the view runs"""
    response = rest_api.post(RACK_MOUNTS_URL, json={'kind': 'MOUNT', 'area': 'UNASSIGNED'})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', GATED_READ_URLS)
@pytest.mark.usefixtures('seeded_rack')
def test_rack_read_routes_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """With IPAM licensed the blueprint guard lets the request through - it is no longer a 403

    Also the regression guard for the registration-order trap: a gate installed after the blueprint
    was registered would never fire, and the unlicensed tests above would fail instead of these.
    """
    _license_ipam(monkeypatch)

    assert rest_api.get(url).status_code != HTTPStatus.FORBIDDEN

# -------------------------------------------------------------------------------------------------------------------- #
#                                          the RACK CmdbType write                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_creating_a_rack_type_blocked_without_license(rest_api) -> None:
    """A RACK SpecialType may not be created while IPAM is unlicensed"""
    response = rest_api.post(f'{TYPES_URL}/', json=_rack_type_doc())

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_rack')
def test_editing_a_rack_type_blocked_without_license(rest_api) -> None:
    """An existing RACK SpecialType may not be edited either - the STORED marker is gated"""
    response = rest_api.put(f'{TYPES_URL}/{RACK_TYPE_ID}', json=_rack_type_doc())

    assert response.status_code == HTTPStatus.FORBIDDEN

# -------------------------------------------------------------------------------------------------------------------- #
#                                          the Rack CmdbObject write                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('seeded_rack')
def test_creating_a_rack_object_blocked_without_license(rest_api) -> None:
    """A Rack object may not be created while IPAM is unlicensed"""
    response = rest_api.post(f'{OBJECTS_URL}/', json=_rack_object_payload())

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_rack')
def test_deleting_a_rack_object_blocked_without_license(rest_api) -> None:
    """Deleting a Rack object is gated on the same policy"""
    response = rest_api.delete(f'{OBJECTS_URL}/{RACK_OBJECT_ID}')

    assert response.status_code == HTTPStatus.FORBIDDEN
