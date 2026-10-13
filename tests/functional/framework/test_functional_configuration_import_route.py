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
Functional tests of POST /configuration_transfer/import through the real REST app

The import writes, so it never runs against the session database: the managers' tenant resolver is pointed at a
scratch target (the requesting user is still read from the session database). The file is produced by exporting a
seeded scratch source through the real components. What is pinned: any user but the administrator account is a 403
before the upload is read; a missing or undecodable file, a target that is not reset and a file with problems are
400s naming the reason; a target without a version is a 500; the administrator's import answers the count per
component and leaves the configuration stored under its ids with the predefined templates seeded and the settings
cleared; a write that fails is a 500 and the target is exactly as before; a file of an older version is migrated and
imported without leaving a staging database, a newer one refused; a type's copy of a predefined template is
reconciled on import and a conflicting copy refused
"""
import json
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from io import BytesIO
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.json_codec import default
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.manager import CategoriesManager, SectionTemplatesManager, SettingsManager, TypesManager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.manager.relations_manager import RelationsManager
from cmdb.framework.configuration_transfer import (
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TransferFileKey,
    TypeComponent,
    export_configuration,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.category_model import CmdbCategory
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.framework.configuration_transfer.configuration_transfer_constants import STAGING_DATABASE_PREFIX
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    ADMIN_ONLY_MESSAGE,
    IMPORT_UPLOAD_FIELD,
    NO_DB_VERSION_MESSAGE,
    NO_IMPORT_FILE_MESSAGE,
    ImportResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

IMPORT_URL: str = '/configuration_transfer/import'
MULTIPART: str = 'multipart/form-data'
PUBLIC_ID_KEY: str = 'public_id'
SOURCE_SUFFIX: str = '-import-route-source'
TARGET_SUFFIX: str = '-import-route-target'
DB_VERSION: int = 20261014
ADMIN_GROUP_ID: int = 1
SECOND_ADMIN_ID: int = 93997

ROUTER: dict[str, Any] = {
    'public_id': 4, 'name': 'router', 'label': 'Router', 'active': True, 'version': '1.0.0', 'author_id': 1,
    'selectable_as_parent': True, 'global_template_ids': [],
    'fields': [{'type': 'text', 'name': 'host', 'label': 'Host'}],
    'render_meta': {'icon': 'fa fa-cube', 'externals': [], 'summary': {'fields': []},
                    'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
}
CATEGORY: dict[str, Any] = {'public_id': 7, 'name': 'network', 'label': 'Network', 'parent': None, 'types': [4],
                            'meta': {'icon': '', 'order': None}}
RELATION: dict[str, Any] = {'public_id': 2, 'relation_name': 'peers', 'relation_name_parent': 'peers with',
                            'relation_name_child': 'is peered by', 'parent_type_ids': [4], 'child_type_ids': [4],
                            'sections': [], 'fields': []}


@pytest.fixture(name='databases')
def fixture_databases(database_manager: MongoDatabaseManager, database_name: str,
                      monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    """A seeded source; a reset target with a version and a user setting; the managers routed to the target"""
    source, target = f'{database_name}{SOURCE_SUFFIX}', f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client

    for name in (source, target):
        client.drop_database(name)

    for collection, rows in ((CmdbType.COLLECTION, [ROUTER]), (CmdbCategory.COLLECTION, [CATEGORY]),
                             (CmdbRelation.COLLECTION, [RELATION])):
        client[source][collection].insert_many(deepcopy(rows))

    SettingsManager(database_manager, target).write(UpdaterSetting.SECTION.value,
                                                    {UpdaterSetting.VERSION.value: DB_VERSION})
    client[target][CmdbUserSetting.COLLECTION].insert_one({PUBLIC_ID_KEY: 1, 'user_id': 1, 'resource': 'x'})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: target))

    yield source, target

    for name in (source, target):
        client.drop_database(name)


@pytest.fixture(name='second_admin')
def fixture_second_admin(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[CmdbUser]:
    """An active member of the admin group who is not the administrator account"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({PUBLIC_ID_KEY: SECOND_ADMIN_ID})
    users.insert_one({PUBLIC_ID_KEY: SECOND_ADMIN_ID, 'user_name': 'import-second-admin', 'active': True,
                      'group_id': ADMIN_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=SECOND_ADMIN_ID, user_name='import-second-admin', active=True, group_id=ADMIN_GROUP_ID)

    users.delete_many({PUBLIC_ID_KEY: SECOND_ADMIN_ID})


def _export(database_manager: MongoDatabaseManager, source: str) -> dict[str, Any]:
    """The source's transfer file"""
    return export_configuration([
        SectionTemplateComponent(SectionTemplatesManager(database_manager, source)),
        TypeComponent(TypesManager(database_manager, source)),
        CategoryComponent(CategoriesManager(database_manager, source)),
        RelationComponent(RelationsManager(database_manager, source)),
    ], DB_VERSION)


def _post(rest_api, content: bytes | None, **kwargs: Any) -> Any:
    """Uploads the content as the transfer file (or no file)"""
    data: dict[str, Any] = {} if content is None else {IMPORT_UPLOAD_FIELD: (BytesIO(content), 'transfer.json')}

    return rest_api.post(IMPORT_URL, data=data, content_type=MULTIPART, **kwargs)


def _upload(rest_api, transfer_file: dict[str, Any]) -> Any:
    """Uploads a transfer file, encoded the way the export encodes it"""
    return _post(rest_api, json.dumps(transfer_file, default=default).encode('utf-8'))


def _message(response: Any) -> str:
    """The error message"""
    return response.get_json()['message']


def _stored(database_manager: MongoDatabaseManager, target: str, collection: str) -> list[dict[str, Any]]:
    """A target collection's documents, without `_id`"""
    return list(database_manager.get_collection(collection, target).find({}, {'_id': 0}, sort=[(PUBLIC_ID_KEY, 1)]))

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       refusals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('databases')
class TestRefusals:
    """Answered before anything is written"""

    def test_a_member_of_the_admin_group_is_a_403_before_the_upload(self, rest_api, second_admin: CmdbUser) -> None:
        """Not the administrator account -> 403, whatever is uploaded"""
        response = _post(rest_api, b'{not json', user=second_admin)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _message(response) == ADMIN_ONLY_MESSAGE

    def test_no_file_is_a_400(self, rest_api) -> None:
        """No multipart field"""
        response = _post(rest_api, None)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == NO_IMPORT_FILE_MESSAGE

    def test_a_file_that_is_no_json_is_a_400(self, rest_api) -> None:
        """Broken JSON"""
        response = _post(rest_api, b'{not json')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'not valid UTF-8 JSON' in _message(response)

    def test_a_target_that_is_not_reset_is_a_400_naming_the_collections(
            self, rest_api, database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
        """A type left on the target -> refused, the collection named; nothing written"""
        source, target = databases
        database_manager.get_collection(CmdbType.COLLECTION, target).insert_one({PUBLIC_ID_KEY: 50, 'name': 'left'})

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert CmdbType.COLLECTION in _message(response)
        assert not _stored(database_manager, target, CmdbCategory.COLLECTION)

    def test_a_target_without_a_version_is_a_500(self, rest_api, database_manager: MongoDatabaseManager,
                                                 databases: tuple[str, str]) -> None:
        """No updater version -> the file cannot be judged"""
        source, target = databases
        SettingsManager(database_manager, target).delete_section(UpdaterSetting.SECTION.value)

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _message(response) == NO_DB_VERSION_MESSAGE

    def test_a_file_of_a_newer_version_is_a_400(self, rest_api, database_manager: MongoDatabaseManager,
                                                databases: tuple[str, str]) -> None:
        """Nothing could migrate a file from the future - both versions named; nothing written"""
        source, target = databases
        transfer_file: dict[str, Any] = _export(database_manager, source)
        transfer_file[TransferFileKey.DB_VERSION.value] = DB_VERSION + 1

        response = _upload(rest_api, transfer_file)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(DB_VERSION + 1) in _message(response) and str(DB_VERSION) in _message(response)
        assert not _stored(database_manager, target, CmdbType.COLLECTION)

    def test_a_file_with_problems_is_a_400_listing_them(self, rest_api, database_manager: MongoDatabaseManager,
                                                        databases: tuple[str, str]) -> None:
        """A category naming a type the file lacks and a relation doing the same - both listed; nothing written"""
        source, target = databases
        transfer_file: dict[str, Any] = _export(database_manager, source)
        sections: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]
        sections['categories']['items'][0]['types'] = [99]
        sections['relations']['items'][0]['child_type_ids'] = [98]

        response = _upload(rest_api, transfer_file)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'categories 7: ' in _message(response) and 'relations 2: ' in _message(response)
        assert not _stored(database_manager, target, CmdbType.COLLECTION)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      the import                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

class TestTheImport:
    """The administrator's import into a reset target"""

    def test_answers_the_count_per_component_and_stores_the_configuration(
            self, rest_api, database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
        """Counts in import order; category and relation as exported; the type under its id"""
        source, target = databases

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.OK
        assert list(response.get_json()[ImportResponseKey.IMPORTED.value].items()) == [
            ('section_templates', 0), ('types', 1), ('categories', 1), ('relations', 1),
        ]
        assert _stored(database_manager, target, CmdbCategory.COLLECTION) == [CATEGORY]
        assert _stored(database_manager, target, CmdbRelation.COLLECTION) == [RELATION]
        assert [row[PUBLIC_ID_KEY] for row in _stored(database_manager, target, CmdbType.COLLECTION)] == [4]

    def test_seeds_the_predefined_templates_and_clears_the_settings(
            self, rest_api, database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
        """Predefined templates present afterwards; the setting written after the reset gone"""
        source, target = databases

        _upload(rest_api, _export(database_manager, source))

        assert [row for row in _stored(database_manager, target, CmdbSectionTemplate.COLLECTION)
                if row.get('predefined') is True]
        assert not _stored(database_manager, target, CmdbUserSetting.COLLECTION)

    def test_a_failing_write_is_a_500_and_the_target_is_unchanged(
            self, rest_api, database_manager: MongoDatabaseManager, databases: tuple[str, str],
            monkeypatch: pytest.MonkeyPatch) -> None:
        """The relations fail: 500 saying nothing was imported; types, templates and settings as before"""
        source, target = databases
        transfer_file: dict[str, Any] = _export(database_manager, source)
        settings_before: list[dict[str, Any]] = _stored(database_manager, target, CmdbUserSetting.COLLECTION)
        original = BaseManager.insert_many

        def _failing_on_relations(self, data: list[dict[str, Any]], skip_public: bool = False) -> list[int]:
            if self.collection == CmdbRelation.COLLECTION:
                raise RuntimeError('relations unavailable')

            return original(self, data, skip_public)

        monkeypatch.setattr(BaseManager, 'insert_many', _failing_on_relations)

        response = _upload(rest_api, transfer_file)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'nothing was imported' in _message(response)
        assert not _stored(database_manager, target, CmdbType.COLLECTION)
        assert not _stored(database_manager, target, CmdbSectionTemplate.COLLECTION)
        assert _stored(database_manager, target, CmdbUserSetting.COLLECTION) == settings_before

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the round trip                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

ROUND_TRIP_SUFFIX: str = '-round-trip'
RESET_URL: str = '/configuration_transfer/reset'
EXPORT_URL: str = '/configuration_transfer/export'
CONFIGURATION: tuple[str, ...] = (CmdbCategory.COLLECTION, CmdbRelation.COLLECTION)


@pytest.fixture(name='round_trip')
def fixture_round_trip(database_manager: MongoDatabaseManager, database_name: str,
                       monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """One scratch system: the configuration, the admin group (the export's right check reads it), a version"""
    system: str = f'{database_name}{ROUND_TRIP_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(system)

    for collection, rows in ((CmdbType.COLLECTION, [ROUTER]), (CmdbCategory.COLLECTION, [CATEGORY]),
                             (CmdbRelation.COLLECTION, [RELATION])):
        client[system][collection].insert_many(deepcopy(rows))

    client[system][CmdbUserGroup.COLLECTION].insert_one({PUBLIC_ID_KEY: ADMIN_GROUP_ID, 'name': 'admin',
                                                     'label': 'Admin', 'rights': ['base.*']})
    SettingsManager(database_manager, system).write(UpdaterSetting.SECTION.value,
                                                    {UpdaterSetting.VERSION.value: DB_VERSION})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: system))

    yield system

    client.drop_database(system)


def test_export_reset_import_gives_back_the_same_configuration(rest_api, database_manager: MongoDatabaseManager,
                                                               round_trip: str) -> None:
    """Over HTTP: the file the export answers, imported after a reset, restores the configuration and its ids"""
    before: dict[str, list[dict[str, Any]]] = {name: _stored(database_manager, round_trip, name)
                                               for name in CONFIGURATION}
    exported = rest_api.get(EXPORT_URL)

    assert exported.status_code == HTTPStatus.OK
    assert rest_api.post(RESET_URL, json={'confirm': 'RESET'}).status_code == HTTPStatus.OK
    assert not _stored(database_manager, round_trip, CmdbType.COLLECTION)

    imported = _post(rest_api, exported.get_data())

    assert imported.status_code == HTTPStatus.OK
    assert {name: _stored(database_manager, round_trip, name) for name in CONFIGURATION} == before
    assert [row['name'] for row in _stored(database_manager, round_trip, CmdbType.COLLECTION)] == [ROUTER['name']]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               older files and templates                                              #
# -------------------------------------------------------------------------------------------------------------------- #

OLDER_VERSION: int = 20261009
MODELSPEC: str = 'dg-modelspec'


def _staging_databases(database_manager: MongoDatabaseManager) -> set[str]:
    """Every database carrying the staging prefix"""
    return {name for name in database_manager.connector.client.list_database_names()
            if name.startswith(STAGING_DATABASE_PREFIX)}


def test_an_older_file_is_migrated_and_imported(rest_api, database_manager: MongoDatabaseManager,
                                                databases: tuple[str, str]) -> None:
    """A version-20261009 file with a dead category type id: the 20261010 updater removes it, the import passes"""
    source, target = databases
    transfer_file: dict[str, Any] = _export(database_manager, source)
    transfer_file[TransferFileKey.DB_VERSION.value] = OLDER_VERSION
    transfer_file[TransferFileKey.COMPONENTS.value]['categories']['items'][0]['types'] = [4, 99]
    staging_before: set[str] = _staging_databases(database_manager)

    response = _upload(rest_api, transfer_file)

    assert response.status_code == HTTPStatus.OK
    assert _stored(database_manager, target, CmdbCategory.COLLECTION)[0]['types'] == [4]
    assert _staging_databases(database_manager) == staging_before


def test_a_template_copy_conflict_is_a_400(rest_api, database_manager: MongoDatabaseManager,
                                           databases: tuple[str, str]) -> None:
    """A field of the type's own inside the dg-modelspec section: refused, type and field named; nothing written"""
    source, target = databases
    transfer_file: dict[str, Any] = _export(database_manager, source)
    router: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]['types']['items'][0]
    router['global_template_ids'] = [MODELSPEC]
    router['render_meta']['sections'] = [{'type': 'section', 'name': MODELSPEC, 'label': 'Model', 'fields': ['host']}]

    response = _upload(rest_api, transfer_file)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "types 4: the field 'host'" in _message(response) and MODELSPEC in _message(response)
    assert not _stored(database_manager, target, CmdbType.COLLECTION)


def test_a_claimed_predefined_template_is_reconciled_on_import(rest_api, database_manager: MongoDatabaseManager,
                                                               databases: tuple[str, str]) -> None:
    """A type claiming dg-modelspec without carrying it is stored with today's section and fields"""
    source, target = databases
    transfer_file: dict[str, Any] = _export(database_manager, source)
    transfer_file[TransferFileKey.COMPONENTS.value]['types']['items'][0]['global_template_ids'] = [MODELSPEC]

    assert _upload(rest_api, transfer_file).status_code == HTTPStatus.OK

    router: dict[str, Any] = _stored(database_manager, target, CmdbType.COLLECTION)[0]
    assert MODELSPEC in [section['name'] for section in router['render_meta']['sections']]
    assert 'dg-modelspec-serial' in [field['name'] for field in router['fields']]
