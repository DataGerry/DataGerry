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
Who may import: the audience of the /import/object, /import/type and /isms/importer routes

**The rule: each import right is a capability of its own.** ``base.import.object.*`` imports objects,
``base.import.type.*`` imports types and ``base.isms.import.add`` imports ISMS catalogue rows - and each
is enough on its own. The importer does not also ask for the framework right a hand-made write would
need (``base.framework.object.add``, ``base.framework.type.add`` / ``.edit``); an administrator grants
import deliberately, and no seeded group holds it. What an object import DOES still check is the target
type's ACL and its active flag, which ``test_functional_importer_object_route.py`` covers.

Pinned from both sides, because either half could be "corrected" away on its own:

* a member of the seeded ``user`` group - who holds ``base.framework.object.*`` - is refused on every
  importer route, so a framework right is not a stand-in for an import right
* a group holding ONLY one import right gets through that right's routes and is refused on the others,
  so the rights are distinct and none of them needs a framework right beside it
"""
import io
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.importer_routes.importer_constants import ImporterRight
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_IMPORT_URL: str = '/import/object'
TYPE_IMPORT_URL: str = '/import/type'
ISMS_IMPORT_URL: str = '/isms/importer/threat'

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

TARGET_TYPE_ID: int = 88801
IMPORTED_TYPE_NAME: str = 'import-rights-imported-type'
CSV_BODY: bytes = b'dg-name\nhost-1\n'

DEFAULT_USER_ID: int = 88811
OBJECT_IMPORTER_USER_ID: int = 88812
TYPE_IMPORTER_USER_ID: int = 88813
ISMS_IMPORTER_USER_ID: int = 88814
OBJECT_IMPORTER_GROUP_ID: int = 88822
TYPE_IMPORTER_GROUP_ID: int = 88823
ISMS_IMPORTER_GROUP_ID: int = 88824

ALL_USER_IDS: list[int] = [DEFAULT_USER_ID, OBJECT_IMPORTER_USER_ID, TYPE_IMPORTER_USER_ID, ISMS_IMPORTER_USER_ID]
ALL_GROUP_IDS: list[int] = [OBJECT_IMPORTER_GROUP_ID, TYPE_IMPORTER_GROUP_ID, ISMS_IMPORTER_GROUP_ID]

# Every importer route, the method it answers and the right it must demand. A refused request never
# reaches the body parsing, so none of them needs a valid payload to be refused
GUARDED_ROUTES: list[tuple[str, str, str, str]] = [
    ('object-importers', 'GET', f'{OBJECT_IMPORT_URL}/importer/', ImporterRight.OBJECT.value),
    ('object-importer-config', 'GET', f'{OBJECT_IMPORT_URL}/importer/config/csv/', ImporterRight.OBJECT.value),
    ('object-parser-config', 'GET', f'{OBJECT_IMPORT_URL}/parser/default/csv/', ImporterRight.OBJECT.value),
    ('object-parse', 'POST', f'{OBJECT_IMPORT_URL}/parse/', ImporterRight.OBJECT.value),
    ('object-import', 'POST', f'{OBJECT_IMPORT_URL}/', ImporterRight.OBJECT.value),
    ('type-create', 'POST', f'{TYPE_IMPORT_URL}/create/', ImporterRight.TYPE.value),
    ('type-update', 'POST', f'{TYPE_IMPORT_URL}/update/', ImporterRight.TYPE.value),
    ('isms-import', 'POST', ISMS_IMPORT_URL, ImporterRight.ISMS_ADD.value),
]

ROUTE_IDS: list[str] = [route[0] for route in GUARDED_ROUTES]


def _call(rest_api, method: str, url: str, user: CmdbUser):
    """Sends one request as `user`, through the client verb that authenticates it."""
    return getattr(rest_api, method.lower())(url, user=user)


def _routes_of(right: str) -> list[tuple[str, str, str, str]]:
    """The guarded routes that demand `right`."""
    return [route for route in GUARDED_ROUTES if route[3] == right]


def _routes_not_of(right: str) -> list[tuple[str, str, str, str]]:
    """The guarded routes that demand some other right."""
    return [route for route in GUARDED_ROUTES if route[3] != right]


def _insert_user(database_manager: MongoDatabaseManager, database_name: str,
                 public_id: int, group_id: int) -> CmdbUser:
    """Stores an active CmdbUser in the given group and returns the model the test client sends as."""
    user_name: str = f'import-rights-{public_id}'
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': public_id,
        'user_name': user_name,
        'active': True,
        'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
        'api_level': 2,
        'config_items_limit': 1000,
        'database': database_name,
    })

    return CmdbUser(public_id=public_id, user_name=user_name, active=True, group_id=group_id)


def _insert_group(database_manager: MongoDatabaseManager, database_name: str, public_id: int, right: str) -> None:
    """Stores a group holding exactly one right."""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).insert_one({
        'public_id': public_id, 'name': f'import-rights-{public_id}', 'label': right, 'rights': [right],
    })


@pytest.fixture(name='users', scope='module')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A default-group user and one user per import right, whose group holds that right and nothing else."""
    users_collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups_collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)

    def _purge() -> None:
        users_collection.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        groups_collection.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})

    _purge()
    _insert_group(database_manager, database_name, OBJECT_IMPORTER_GROUP_ID, ImporterRight.OBJECT.value)
    _insert_group(database_manager, database_name, TYPE_IMPORTER_GROUP_ID, ImporterRight.TYPE.value)
    _insert_group(database_manager, database_name, ISMS_IMPORTER_GROUP_ID, ImporterRight.ISMS_ADD.value)

    yield {
        'default': _insert_user(database_manager, database_name, DEFAULT_USER_ID, USER_GROUP_ID),
        ImporterRight.OBJECT.value: _insert_user(
            database_manager, database_name, OBJECT_IMPORTER_USER_ID, OBJECT_IMPORTER_GROUP_ID,
        ),
        ImporterRight.TYPE.value: _insert_user(
            database_manager, database_name, TYPE_IMPORTER_USER_ID, TYPE_IMPORTER_GROUP_ID,
        ),
        ImporterRight.ISMS_ADD.value: _insert_user(
            database_manager, database_name, ISMS_IMPORTER_USER_ID, ISMS_IMPORTER_GROUP_ID,
        ),
    }

    _purge()


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses every feature, so the ISMS route answers its right check rather than its licence gate."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _seed_and_clean(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the import target type; removes it, whatever was imported into it and its logs."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        imported_ids: list[int] = [doc['public_id'] for doc in objects.find({'type_id': TARGET_TYPE_ID})]
        logs.delete_many({'object_id': {'$in': imported_ids}})
        objects.delete_many({'type_id': TARGET_TYPE_ID})
        types.delete_many({'$or': [{'public_id': TARGET_TYPE_ID}, {'name': IMPORTED_TYPE_NAME}]})

    _purge()
    types.insert_one(make_type_doc(TARGET_TYPE_ID, 'import-rights-target'))
    yield
    _purge()


def _object_import_form() -> dict[str, Any]:
    """A one-row CSV import into the target type."""
    return {
        'file': (io.BytesIO(CSV_BODY), 'import.csv'),
        'file_format': 'csv',
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({'type_id': TARGET_TYPE_ID}),
    }


def _type_import_form() -> dict[str, Any]:
    """A one-type upload creating IMPORTED_TYPE_NAME."""
    new_type: dict[str, Any] = make_type_doc(0, IMPORTED_TYPE_NAME)
    new_type.pop('public_id')

    return {'uploadFile': json.dumps([new_type], default=str)}


class TestAFrameworkRightIsNotAnImportRight:
    """A member of the seeded 'user' group holds base.framework.object.* - and is refused everywhere here."""

    @pytest.mark.parametrize('label, method, url, right', GUARDED_ROUTES, ids=ROUTE_IDS)
    def test_every_importer_route_refuses_the_default_user(
        self, rest_api, users: dict[str, CmdbUser], label: str, method: str, url: str, right: str,
    ) -> None:
        """403 naming the route's own right"""
        del label

        response = _call(rest_api, method, url, users['default'])

        assert response.status_code == HTTPStatus.FORBIDDEN, url
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=right)

    def test_a_refused_object_import_writes_nothing(
        self, rest_api, users: dict[str, CmdbUser], database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The right check runs before the upload is read, so no row is stored"""
        response = rest_api.post(f'{OBJECT_IMPORT_URL}/', data=_object_import_form(),
                                 content_type='multipart/form-data', user=users['default'])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .count_documents({'type_id': TARGET_TYPE_ID}) == 0

    def test_a_refused_type_import_writes_nothing(
        self, rest_api, users: dict[str, CmdbUser], database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Nor is a type"""
        response = rest_api.post(f'{TYPE_IMPORT_URL}/create/', data=_type_import_form(),
                                 content_type='multipart/form-data', user=users['default'])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .count_documents({'name': IMPORTED_TYPE_NAME}) == 0


class TestTheImportRightsAreDistinct:
    """A group holding one import right is refused on the routes of the other two."""

    @pytest.mark.parametrize('held', [right.value for right in ImporterRight])
    def test_every_other_importer_route_is_refused(self, rest_api, users: dict[str, CmdbUser], held: str) -> None:
        """Holding one import right grants none of the others"""
        for _label, method, url, right in _routes_not_of(held):
            response = _call(rest_api, method, url, users[held])

            assert response.status_code == HTTPStatus.FORBIDDEN, url
            assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=right)

    @pytest.mark.parametrize('held', [right.value for right in ImporterRight])
    def test_its_own_routes_are_not_refused(self, rest_api, users: dict[str, CmdbUser], held: str) -> None:
        """
        The right alone passes the check on its own routes

        A request without a body is answered by the route itself - 400 for a missing upload, 200 for a
        catalogue - which is the point: whatever comes back, it is not the right check refusing
        """
        for _label, method, url, _right in _routes_of(held):
            assert _call(rest_api, method, url, users[held]).status_code != HTTPStatus.FORBIDDEN, url


class TestAnImportRightIsEnoughOnItsOwn:
    """The ruling: no framework right is needed beside an import right."""

    def test_the_object_import_right_alone_imports_objects(
        self, rest_api, users: dict[str, CmdbUser], database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A group with base.import.object.* and nothing else - no base.framework.object.add - imports"""
        importer: CmdbUser = users[ImporterRight.OBJECT.value]

        response = rest_api.post(f'{OBJECT_IMPORT_URL}/', data=_object_import_form(),
                                 content_type='multipart/form-data', user=importer)

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'type_id': TARGET_TYPE_ID})
        assert stored is not None
        assert stored['author_id'] == importer.public_id

    def test_the_type_import_right_alone_imports_types(
        self, rest_api, users: dict[str, CmdbUser], database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A group with base.import.type.* and nothing else - no base.framework.type.add - imports"""
        response = rest_api.post(f'{TYPE_IMPORT_URL}/create/', data=_type_import_form(),
                                 content_type='multipart/form-data', user=users[ImporterRight.TYPE.value])

        assert response.status_code == HTTPStatus.OK
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .count_documents({'name': IMPORTED_TYPE_NAME}) == 1
