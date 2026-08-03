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
Functional tests for IPAM importer feature-gating over HTTP (license feature P15, Step 8)

The bulk object importer bypasses enforce_object_invariants, so it carries its own guard: importing
objects whose target CmdbType is an IPAM special type is rejected with HTTP 403 when IPAM is not
licensed (the guard fires right after the type is resolved, before any parsing). Importing into an
ordinary type is never gated. When IPAM is licensed the import proceeds past the guard

The TYPE importer carries the same gate in its own shape: uploading a CmdbType that declares a
special_type would install an IPAM type outright, so an unlicensed instance reports that entry in the
partial-report body (HTTP 200 + a per-entry error) rather than aborting the whole upload.
"""
import json
from http import HTTPStatus
from io import BytesIO
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

IMPORT_URL: str = '/import/object/'
TYPE_IMPORT_URL: str = '/import/type/create/'

IMPORTED_TYPE_NAME: str = 'lic-import-uploaded-special'

SPECIAL_TYPE_ID: int = 47201
NORMAL_TYPE_ID: int = 47202


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an active IPAM special type and an active normal type, cleaning up after each test"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_many([
        make_type_doc(SPECIAL_TYPE_ID, 'lic-import-special', SpecialType.SUBNET),
        make_type_doc(NORMAL_TYPE_ID, 'lic-import-normal', None),
    ])
    yield
    types.delete_many({'public_id': {'$in': [SPECIAL_TYPE_ID, NORMAL_TYPE_ID]}})


def _import_form(type_id: int) -> dict[str, Any]:
    """Builds the multipart import form data targeting the given type"""
    return {
        'file': (BytesIO(b'dg-name\nhost-1\n'), 'import.csv'),
        'file_format': 'csv',
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({'type_id': type_id}),
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_import_into_special_type_blocked_without_license(rest_api) -> None:
    """Importing objects into an IPAM special type is blocked with 403 when IPAM is not licensed"""
    response = rest_api.post(IMPORT_URL, data=_import_form(SPECIAL_TYPE_ID), content_type='multipart/form-data')

    assert response.status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          ordinary imports stay usable                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_import_into_normal_type_allowed_without_license(rest_api) -> None:
    """Importing into an ordinary type is NOT gated - it never returns the guard 403"""
    response = rest_api.post(IMPORT_URL, data=_import_form(NORMAL_TYPE_ID), content_type='multipart/form-data')

    assert response.status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_import_into_special_type_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With IPAM licensed, an import into a special type passes the guard (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )

    response = rest_api.post(IMPORT_URL, data=_import_form(SPECIAL_TYPE_ID), content_type='multipart/form-data')

    assert response.status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          type import: same gate, per entry                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def _type_upload(special_type: str | None) -> dict[str, Any]:
    """Builds the type-import form carrying a single uploaded type."""
    payload = make_type_doc(0, IMPORTED_TYPE_NAME, special_type)
    payload.pop('public_id')

    return {'uploadFile': json.dumps([payload], default=str)}


def _type_import_errors(response) -> list[str]:
    """Every error message the type import's partial report collected."""
    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


def test_uploading_special_type_blocked_without_license(
    rest_api, database_manager: MongoDatabaseManager, database_name: str
) -> None:
    """An uploaded special type is reported per entry and never inserted when IPAM is unlicensed."""
    response = rest_api.post(
        TYPE_IMPORT_URL, data=_type_upload(SpecialType.SUBNET), content_type='multipart/form-data'
    )

    assert response.status_code == HTTPStatus.OK  # partial report, not an abort
    (message,) = _type_import_errors(response)
    assert 'not licensed' in message
    stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .find_one({'name': IMPORTED_TYPE_NAME})
    assert stored is None


def test_uploading_ordinary_type_allowed_without_license(
    rest_api, database_manager: MongoDatabaseManager, database_name: str
) -> None:
    """A type carrying no special_type imports normally on an unlicensed instance."""
    response = rest_api.post(TYPE_IMPORT_URL, data=_type_upload(None), content_type='multipart/form-data')

    assert response.status_code == HTTPStatus.OK
    assert _type_import_errors(response) == []
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    assert types.find_one({'name': IMPORTED_TYPE_NAME}) is not None
    types.delete_many({'name': IMPORTED_TYPE_NAME})


def test_uploading_special_type_allowed_when_licensed(
    rest_api, database_manager: MongoDatabaseManager, database_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With IPAM licensed the uploaded special type is imported like any other.

    Uses SUPERNET rather than SUBNET: the seeded type already claims SUBNET, and a special type can
    only exist once, so a second SUBNET would be refused by the uniqueness rule instead of the licence.
    """
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )

    response = rest_api.post(
        TYPE_IMPORT_URL, data=_type_upload(SpecialType.SUPERNET), content_type='multipart/form-data'
    )

    assert response.status_code == HTTPStatus.OK
    assert _type_import_errors(response) == []
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    assert types.find_one({'name': IMPORTED_TYPE_NAME}) is not None
    types.delete_many({'name': IMPORTED_TYPE_NAME})
