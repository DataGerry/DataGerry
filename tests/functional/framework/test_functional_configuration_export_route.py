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
Functional tests of GET /configuration_transfer/export through the real REST app

Read-only, so it runs against the session database, given an updater version for the time of the test (the session
setup runs no updater, so it records none). What is pinned: no
token is a 401, a group without `base.system.export` a 403 and a group holding only that right passes; the answer is
a JSON attachment named by the database version whose envelope passes the import's own check, stamped with the
database's updater version; a seeded type comes back as stored (a datetime as `{'$date': millis}`), the components
come in ascending public_id order and the predefined section templates stay out; a database without a version is
refused with a 500 that says so
"""
import re
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.manager import SettingsManager
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENT_NAMES,
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
    find_transfer_file_problems,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.utils import CONTENT_DISPOSITION_HEADER
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_EXPORT_MIMETYPE,
    CONFIGURATION_EXPORT_RIGHT,
    NO_DB_VERSION_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_URL: str = '/configuration_transfer/export'
PUBLIC_ID_KEY: str = 'public_id'

EXPORTER_GROUP_ID: int = 93990
EXPORTER_USER_ID: int = 93991
RIGHTLESS_GROUP_ID: int = 93992
RIGHTLESS_USER_ID: int = 93993
SEEDED_TYPE_ID: int = 93994
SEEDED_TYPE_NAME: str = 'export-route-seeded'
PREDEFINED_TEMPLATE_ID: int = 93995
USER_TEMPLATE_ID: int = 93996
PREDEFINED_FLAG: str = SectionTemplateKey.PREDEFINED.value
CREATED: datetime = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
CREATED_MILLIS: int = int(CREATED.timestamp() * 1000)
DB_VERSION: int = 20261014
ROUTES_MODULE: str = (
    'cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_routes'
)


@pytest.fixture(name='db_version', autouse=True)
def fixture_db_version(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[int]:
    """The session database's updater version - recorded for the test when it has none, and removed again"""
    settings: SettingsManager = SettingsManager(database_manager, database_name)
    stored: dict[str, Any] | None = settings.get_section(UpdaterSetting.SECTION.value)

    if stored is None:
        settings.write(UpdaterSetting.SECTION.value, {UpdaterSetting.VERSION.value: DB_VERSION})

    yield stored[UpdaterSetting.VERSION.value] if stored else DB_VERSION

    if stored is None:
        settings.delete_section(UpdaterSetting.SECTION.value)


def _seed_user(database_manager: MongoDatabaseManager, database_name: str, group_id: int, user_id: int,
               rights: list[str]) -> CmdbUser:
    """A group holding exactly the given rights and an active user in it"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups.delete_many({PUBLIC_ID_KEY: group_id})
    users.delete_many({PUBLIC_ID_KEY: user_id})
    groups.insert_one({PUBLIC_ID_KEY: group_id, 'name': f'export-group-{group_id}', 'label': 'Export',
                       'rights': rights})
    users.insert_one({PUBLIC_ID_KEY: user_id, 'user_name': f'export-user-{user_id}', 'active': True,
                      'group_id': group_id, 'registration_time': datetime.now(timezone.utc)})

    return CmdbUser(public_id=user_id, user_name=f'export-user-{user_id}', active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[CmdbUser, CmdbUser]]:
    """A user whose group holds only the export right, and one whose group holds no right"""
    exporter: CmdbUser = _seed_user(database_manager, database_name, EXPORTER_GROUP_ID, EXPORTER_USER_ID,
                                    [CONFIGURATION_EXPORT_RIGHT])
    rightless: CmdbUser = _seed_user(database_manager, database_name, RIGHTLESS_GROUP_ID, RIGHTLESS_USER_ID, [])

    yield exporter, rightless

    for collection, ids in ((CmdbUser.COLLECTION, [EXPORTER_USER_ID, RIGHTLESS_USER_ID]),
                            (CmdbUserGroup.COLLECTION, [EXPORTER_GROUP_ID, RIGHTLESS_GROUP_ID])):
        database_manager.get_collection(collection, database_name).delete_many({PUBLIC_ID_KEY: {'$in': ids}})


@pytest.fixture(name='seeded_type')
def fixture_seeded_type(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A type in the session database, with a datetime"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({PUBLIC_ID_KEY: SEEDED_TYPE_ID})
    types.insert_one({PUBLIC_ID_KEY: SEEDED_TYPE_ID, 'name': SEEDED_TYPE_NAME, 'creation_time': CREATED})

    yield

    types.delete_many({PUBLIC_ID_KEY: SEEDED_TYPE_ID})


def _items(body: dict[str, Any], name: TransferComponentName) -> list[dict[str, Any]]:
    """A component's exported documents"""
    return body[TransferFileKey.COMPONENTS.value][name.value][TransferSectionKey.ITEMS.value]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        access                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

class TestAccess:
    """Who may export"""

    def test_no_token_is_a_401(self, rest_api) -> None:
        """No Authorization header -> 401"""
        assert rest_api.get(EXPORT_URL, environ_overrides={'HTTP_AUTHORIZATION': ''}).status_code == \
            HTTPStatus.UNAUTHORIZED

    def test_a_group_without_the_right_is_a_403(self, rest_api, users: tuple[CmdbUser, CmdbUser]) -> None:
        """The refusal names the right"""
        response = rest_api.get(EXPORT_URL, user=users[1])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert CONFIGURATION_EXPORT_RIGHT in response.get_json()['message']

    def test_the_export_right_alone_is_enough(self, rest_api, users: tuple[CmdbUser, CmdbUser]) -> None:
        """Not the administrator account, not the admin group - just the right"""
        assert rest_api.get(EXPORT_URL, user=users[0]).status_code == HTTPStatus.OK

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the file                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('seeded_type')
class TestTheFile:
    """What the export answers"""

    def test_is_a_json_attachment_named_by_the_version(self, rest_api, db_version: int) -> None:
        """JSON, attachment, `..._configuration_db-<version>.json`, the same version in the body"""
        version: int = db_version
        response = rest_api.get(EXPORT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.mimetype == CONFIGURATION_EXPORT_MIMETYPE
        assert re.search(f'attachment; filename="[^"]*_configuration_db-{version}\\.json"',
                         response.headers[CONTENT_DISPOSITION_HEADER])
        assert response.get_json()[TransferFileKey.DB_VERSION.value] == version

    def test_passes_the_imports_envelope_check(self, rest_api) -> None:
        """What the export writes, the import's envelope check accepts"""
        assert not find_transfer_file_problems(rest_api.get(EXPORT_URL).get_json(), TRANSFER_COMPONENT_NAMES)

    def test_carries_a_stored_type_as_stored(self, rest_api) -> None:
        """The seeded type with its keys; its datetime as {'$date': millis}; no _id"""
        types: list[dict[str, Any]] = _items(rest_api.get(EXPORT_URL).get_json(), TransferComponentName.TYPES)

        assert {PUBLIC_ID_KEY: SEEDED_TYPE_ID, 'name': SEEDED_TYPE_NAME,
                'creation_time': {'$date': CREATED_MILLIS}} in types

    def test_every_component_is_in_ascending_public_id_order(self, rest_api) -> None:
        """Two exports of the same system diff cleanly"""
        body: dict[str, Any] = rest_api.get(EXPORT_URL).get_json()

        for name in TransferComponentName:
            ids: list[int] = [item[PUBLIC_ID_KEY] for item in _items(body, name)]
            assert ids == sorted(ids), name

    def test_leaves_the_predefined_section_templates_out(self, rest_api, database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """A predefined template is not exported; a user template beside it is"""
        templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
        seeded: list[int] = [PREDEFINED_TEMPLATE_ID, USER_TEMPLATE_ID]
        templates.delete_many({PUBLIC_ID_KEY: {'$in': seeded}})
        templates.insert_many([
            {PUBLIC_ID_KEY: PREDEFINED_TEMPLATE_ID, 'name': 'export-predefined', PREDEFINED_FLAG: True},
            {PUBLIC_ID_KEY: USER_TEMPLATE_ID, 'name': 'export-user', PREDEFINED_FLAG: False},
        ])

        try:
            exported: set[int] = {item[PUBLIC_ID_KEY] for item in _items(rest_api.get(EXPORT_URL).get_json(),
                                                                           TransferComponentName.SECTION_TEMPLATES)}
        finally:
            templates.delete_many({PUBLIC_ID_KEY: {'$in': seeded}})

        assert USER_TEMPLATE_ID in exported
        assert PREDEFINED_TEMPLATE_ID not in exported


def test_a_database_without_a_version_is_a_500(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """No valid updater version -> no file a system could import; the message says why"""
    monkeypatch.setattr(f'{ROUTES_MODULE}.read_database_version', lambda settings_manager: None)

    response = rest_api.get(EXPORT_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] == NO_DB_VERSION_MESSAGE
