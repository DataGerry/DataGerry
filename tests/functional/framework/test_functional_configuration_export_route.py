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
Functional tests of POST /configuration_transfer/export through the real REST app

Read-only, so it runs against the session database, given an updater version for the time of the test (the session
setup runs no updater, so it records none). What is pinned: no
token is a 401, a group without `base.system.export` a 403 and a group holding only that right passes; the answer is
a JSON attachment named by the database version whose envelope passes the import's own check, stamped with the
database's updater version; a seeded type comes back as stored (a datetime as `{'$date': millis}`), the components
come in ascending public_id order and the predefined section templates stay out; a database without a version is
refused with a 500 that says so. The body: a name is required and every value is held to its kind and length (400);
the file's `information` carries the name, the description, the release and counts that match the components, its
`meta` is empty and names every exported category; a chosen filename names the download - cleaned, or the generated
name when nothing usable is left
"""
import re
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.manager import SettingsManager
from cmdb import __version__
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENT_NAMES,
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
    build_empty_meta,
    find_transfer_file_problems,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    INFORMATION_DESCRIPTION_MAX_LENGTH,
    INFORMATION_NAME_MAX_LENGTH,
)
from cmdb.models.category_model import CmdbCategory
from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.utils import CONTENT_DISPOSITION_HEADER
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_EXPORT_MIMETYPE,
    CONFIGURATION_EXPORT_RIGHT,
    EXPORT_FILENAME_INPUT_MAX_LENGTH,
    NO_DB_VERSION_MESSAGE,
    ExportRequestKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_URL: str = '/configuration_transfer/export'
# The smallest body the export takes: a name
EXPORT_BODY: dict[str, str] = {'name': 'Functional export'}
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
SEEDED_CATEGORY_ID: int = 93997
SEEDED_CATEGORY_NAME: str = 'export-route-category'
EXPORT_NAME: str = 'Customer model'
EXPORT_DESCRIPTION: str = 'Everything a customer installation starts from'
CHOSEN_FILENAME: str = 'Kunden Übersicht'
NAME_KEY: str = ExportRequestKey.NAME.value
DESCRIPTION_KEY: str = ExportRequestKey.DESCRIPTION.value
FILENAME_KEY: str = ExportRequestKey.FILENAME.value
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


def _export(rest_api: Any, **kwargs: Any) -> Any:
    """Exports with the smallest body the route takes - further request options as given"""
    return rest_api.post(EXPORT_URL, json=EXPORT_BODY, **kwargs)


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
        assert _export(rest_api, environ_overrides={'HTTP_AUTHORIZATION': ''}).status_code == \
            HTTPStatus.UNAUTHORIZED

    def test_a_group_without_the_right_is_a_403(self, rest_api, users: tuple[CmdbUser, CmdbUser]) -> None:
        """The refusal names the right"""
        response = _export(rest_api, user=users[1])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert CONFIGURATION_EXPORT_RIGHT in response.get_json()['message']

    def test_the_export_right_alone_is_enough(self, rest_api, users: tuple[CmdbUser, CmdbUser]) -> None:
        """Not the administrator account, not the admin group - just the right"""
        assert _export(rest_api, user=users[0]).status_code == HTTPStatus.OK

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the file                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('seeded_type')
class TestTheFile:
    """What the export answers"""

    def test_is_a_json_attachment_named_by_the_version(self, rest_api, db_version: int) -> None:
        """JSON, attachment, `..._configuration_db-<version>.json`, the same version in the body"""
        version: int = db_version
        response = _export(rest_api)

        assert response.status_code == HTTPStatus.OK
        assert response.mimetype == CONFIGURATION_EXPORT_MIMETYPE
        assert re.search(f'attachment; filename="[^"]*_configuration_db-{version}\\.json"',
                         response.headers[CONTENT_DISPOSITION_HEADER])
        assert response.get_json()[TransferFileKey.DB_VERSION.value] == version

    def test_passes_the_imports_envelope_check(self, rest_api) -> None:
        """What the export writes, the import's envelope check accepts"""
        assert not find_transfer_file_problems(_export(rest_api).get_json(), TRANSFER_COMPONENT_NAMES)

    def test_carries_a_stored_type_as_stored(self, rest_api) -> None:
        """The seeded type with its keys; its datetime as {'$date': millis}; no _id"""
        types: list[dict[str, Any]] = _items(_export(rest_api).get_json(), TransferComponentName.TYPES)

        assert {PUBLIC_ID_KEY: SEEDED_TYPE_ID, 'name': SEEDED_TYPE_NAME,
                'creation_time': {'$date': CREATED_MILLIS}} in types

    def test_every_component_is_in_ascending_public_id_order(self, rest_api) -> None:
        """Two exports of the same system diff cleanly"""
        body: dict[str, Any] = _export(rest_api).get_json()

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
            exported: set[int] = {item[PUBLIC_ID_KEY] for item in _items(_export(rest_api).get_json(),
                                                                         TransferComponentName.SECTION_TEMPLATES)}
        finally:
            templates.delete_many({PUBLIC_ID_KEY: {'$in': seeded}})

        assert USER_TEMPLATE_ID in exported
        assert PREDEFINED_TEMPLATE_ID not in exported


def test_a_database_without_a_version_is_a_500(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """No valid updater version -> no file a system could import; the message says why"""
    monkeypatch.setattr(f'{ROUTES_MODULE}.read_database_version', lambda settings_manager: None)

    response = _export(rest_api)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] == NO_DB_VERSION_MESSAGE

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the body                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.fixture(name='seeded_category')
def fixture_seeded_category(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A category in the session database, so the meta section has one to name"""
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
    categories.delete_many({PUBLIC_ID_KEY: SEEDED_CATEGORY_ID})
    categories.insert_one({PUBLIC_ID_KEY: SEEDED_CATEGORY_ID, CategoryKey.NAME.value: SEEDED_CATEGORY_NAME,
                           CategoryKey.LABEL.value: 'Seeded', CategoryKey.TYPES.value: []})

    yield

    categories.delete_many({PUBLIC_ID_KEY: SEEDED_CATEGORY_ID})


class TestTheBody:
    """A name is required; every value is held to its kind and length"""

    @pytest.mark.parametrize('body,key', [
        ({}, NAME_KEY),
        ({NAME_KEY: ''}, NAME_KEY),
        ({NAME_KEY: '   '}, NAME_KEY),
        ({NAME_KEY: 7}, NAME_KEY),
        ({NAME_KEY: 'x' * (INFORMATION_NAME_MAX_LENGTH + 1)}, NAME_KEY),
        ({**EXPORT_BODY, DESCRIPTION_KEY: 'x' * (INFORMATION_DESCRIPTION_MAX_LENGTH + 1)}, DESCRIPTION_KEY),
        ({**EXPORT_BODY, DESCRIPTION_KEY: ['no', 'text']}, DESCRIPTION_KEY),
        ({**EXPORT_BODY, FILENAME_KEY: 'x' * (EXPORT_FILENAME_INPUT_MAX_LENGTH + 1)}, FILENAME_KEY),
        ({**EXPORT_BODY, FILENAME_KEY: 12}, FILENAME_KEY),
    ], ids=['no-name', 'empty-name', 'blank-name', 'name-number', 'name-too-long', 'description-too-long',
            'description-list', 'filename-too-long', 'filename-number'])
    def test_an_unusable_body_is_a_400_naming_the_key(self, rest_api, body: dict[str, Any], key: str) -> None:
        """Before anything is read"""
        response = rest_api.post(EXPORT_URL, json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert key in response.get_json()['message']

    def test_a_body_that_is_no_object_is_a_400(self, rest_api) -> None:
        """A list instead of the object"""
        assert rest_api.post(EXPORT_URL, json=[EXPORT_NAME]).status_code == HTTPStatus.BAD_REQUEST

    def test_the_limits_themselves_pass(self, rest_api) -> None:
        """A name, a description and a filename of their full length"""
        response = rest_api.post(EXPORT_URL, json={NAME_KEY: 'n' * INFORMATION_NAME_MAX_LENGTH,
                                                   DESCRIPTION_KEY: 'd' * INFORMATION_DESCRIPTION_MAX_LENGTH,
                                                   FILENAME_KEY: 'f' * EXPORT_FILENAME_INPUT_MAX_LENGTH})

        assert response.status_code == HTTPStatus.OK

    def test_an_unknown_key_is_dropped(self, rest_api) -> None:
        """Purged by the validation, never written into the file"""
        response = rest_api.post(EXPORT_URL, json={**EXPORT_BODY, 'stray': 'value'})

        assert response.status_code == HTTPStatus.OK
        assert 'stray' not in response.get_data(as_text=True)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the sections                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('seeded_type', 'seeded_category')
class TestTheSections:
    """What the file says about itself"""

    def test_information_carries_the_users_texts_the_release_and_matching_counts(self, rest_api) -> None:
        """Every count equals its component's entries"""
        body: dict[str, Any] = rest_api.post(EXPORT_URL, json={NAME_KEY: EXPORT_NAME,
                                                               DESCRIPTION_KEY: EXPORT_DESCRIPTION}).get_json()

        assert body[TransferFileKey.INFORMATION.value] == {
            TransferInformationKey.NAME.value: EXPORT_NAME,
            TransferInformationKey.DESCRIPTION.value: EXPORT_DESCRIPTION,
            TransferInformationKey.VERSION.value: __version__,
            TransferInformationKey.COUNTS.value: {
                name: len(body[TransferFileKey.COMPONENTS.value][name][TransferSectionKey.ITEMS.value])
                for name in TRANSFER_COMPONENT_NAMES
            },
        }

    def test_no_description_is_written_as_empty(self, rest_api) -> None:
        """The key is always there"""
        information: dict[str, Any] = _export(rest_api).get_json()[TransferFileKey.INFORMATION.value]

        assert information[TransferInformationKey.DESCRIPTION.value] == ''

    def test_meta_is_empty_and_names_every_exported_category(self, rest_api) -> None:
        """Ready to be filled in by hand - the seeded category among the names"""
        body: dict[str, Any] = _export(rest_api).get_json()
        names: list[str] = [category[CategoryKey.NAME.value] for category in
                            _items(body, TransferComponentName.CATEGORIES)]

        assert SEEDED_CATEGORY_NAME in names
        assert body[TransferFileKey.META.value] == build_empty_meta(names)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the filename                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class TestTheFilename:
    """A chosen filename names the download, cleaned; nothing usable is the generated name"""

    def test_a_chosen_name_names_the_download(self, rest_api) -> None:
        """As typed, `.json` added; the exact spelling in filename*"""
        response = rest_api.post(EXPORT_URL, json={**EXPORT_BODY, FILENAME_KEY: CHOSEN_FILENAME})

        assert response.headers[CONTENT_DISPOSITION_HEADER] == (
            'attachment; filename="Kunden Ubersicht.json"; filename*=UTF-8\'\'Kunden%20%C3%9Cbersicht.json'
        )

    def test_a_path_in_the_name_is_removed(self, rest_api) -> None:
        """No separator reaches the header"""
        response = rest_api.post(EXPORT_URL, json={**EXPORT_BODY, FILENAME_KEY: '../../models/backup'})

        assert response.headers[CONTENT_DISPOSITION_HEADER] == 'attachment; filename="modelsbackup.json"'

    @pytest.mark.parametrize('filename', [None, '', ' . '], ids=['null', 'empty', 'nothing-usable'])
    def test_no_usable_name_is_the_generated_one(self, rest_api, db_version: int, filename: str | None) -> None:
        """Named by the database version"""
        response = rest_api.post(EXPORT_URL, json={**EXPORT_BODY, FILENAME_KEY: filename})

        assert re.search(f'attachment; filename="[^"]*_configuration_db-{db_version}\\.json"',
                         response.headers[CONTENT_DISPOSITION_HEADER])
