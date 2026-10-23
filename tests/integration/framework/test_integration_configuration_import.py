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
Integration tests of the configuration import against a real MongoDB, through the real managers and ledger

A configuration is seeded into a source scratch database and exported; a target scratch database is put in the
state a reset leaves (the predefined templates seeded under the ids the user's template uses in the source, user
settings written since). What is pinned: every document arrives under its exported public_id, the type with the
default ACL and the importer as author; every counter is the exported one; the predefined templates are seeded again
above the template counter, the user settings are gone; and a failure midway is undone completely - the target is
back in its reset state, predefined templates, user settings and counters included
"""
from copy import deepcopy
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.manager import CategoriesManager, SectionTemplatesManager, TypesManager, UserSettingsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.section_templates import SectionTemplateCreator
from cmdb.framework.configuration_transfer import (
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TypeComponent,
    export_configuration,
    import_configuration,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.security.acl.access_control_list import AccessControlList
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

SOURCE_SUFFIX: str = '-import-source'
TARGET_SUFFIX: str = '-import-target'
DB_VERSION: int = 20261014
IMPORTER_ID: int = 1
PUBLIC_ID_KEY: str = 'public_id'
MONGO_ID_KEY: str = '_id'
COUNTER_KEY: str = 'counter'

COUNTERS: dict[str, int] = {
    CmdbSectionTemplate.COLLECTION: 12,
    CmdbType.COLLECTION: 30,
    CmdbCategory.COLLECTION: 8,
    CmdbRelation.COLLECTION: 5,
}
ROUTER: dict[str, Any] = {'public_id': 4, 'name': 'router', 'label': 'Router', 'author_id': 77, 'editor_id': 78,
                          'acl': {'activated': True, 'groups': {'includes': {'5': ['READ']}}}, 'fields': []}
SWITCH: dict[str, Any] = {'public_id': 21, 'name': 'switch', 'label': 'Switch', 'author_id': 77, 'fields': []}
# The user's template takes id 1 - the id the target's first predefined template carries
TEMPLATE: dict[str, Any] = {'public_id': 1, 'name': 'user-template', 'label': 'User', 'predefined': False,
                            'fields': []}
CATEGORY: dict[str, Any] = {'public_id': 7, 'name': 'network', 'types': [4, 21], 'parent': None}
RELATION: dict[str, Any] = {'public_id': 2, 'relation_name': 'uplink', 'parent_type_ids': [4],
                            'child_type_ids': [21]}
SETTINGS: list[dict[str, Any]] = [{'public_id': 1, 'user_id': 1, 'resource': 'table-types'}]


@pytest.fixture(name='databases')
def fixture_databases(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, str]]:
    """A seeded source; a target as a reset leaves it: the predefined templates and settings written since"""
    source, target = f'{database_name}{SOURCE_SUFFIX}', f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client

    for name in (source, target):
        client.drop_database(name)

    for collection, rows in ((CmdbType.COLLECTION, [ROUTER, SWITCH]), (CmdbSectionTemplate.COLLECTION, [TEMPLATE]),
                             (CmdbCategory.COLLECTION, [CATEGORY]), (CmdbRelation.COLLECTION, [RELATION])):
        client[source][collection].insert_many(deepcopy(rows))

    client[source][PUBLIC_ID_COUNTER_COLLECTION].insert_many(
        [{MONGO_ID_KEY: collection, COUNTER_KEY: value} for collection, value in COUNTERS.items()]
    )

    predefined: list[dict[str, Any]] = SectionTemplateCreator().get_predefined_templates()
    for public_id, template in enumerate(predefined, start=1):
        template[PUBLIC_ID_KEY] = public_id

    client[target][CmdbSectionTemplate.COLLECTION].insert_many(predefined)
    client[target][CmdbUserSetting.COLLECTION].insert_many(deepcopy(SETTINGS))
    client[target][PUBLIC_ID_COUNTER_COLLECTION].insert_one(
        {MONGO_ID_KEY: CmdbSectionTemplate.COLLECTION, COUNTER_KEY: len(predefined)}
    )

    yield source, target

    for name in (source, target):
        client.drop_database(name)


def _components(database_manager: MongoDatabaseManager, database: str) -> list[Any]:
    """The four components on one database's managers"""
    return [
        SectionTemplateComponent(SectionTemplatesManager(database_manager, database)),
        TypeComponent(TypesManager(database_manager, database)),
        CategoryComponent(CategoriesManager(database_manager, database)),
        RelationComponent(RelationsManager(database_manager, database)),
    ]


def _import(database_manager: MongoDatabaseManager, source: str, target: str, ledger: WriteLedger) -> dict[str, int]:
    """Exports the source, imports into the target"""
    transfer_file: dict[str, Any] = export_configuration(_components(database_manager, source), DB_VERSION,
                                                         EXPORT_NAME)

    return import_configuration(
        _components(database_manager, target), transfer_file,
        (SectionTemplatesManager(database_manager, target), UserSettingsManager(database_manager, target)),
        ledger, IMPORTER_ID,
    )


def _stored(database_manager: MongoDatabaseManager, database: str, collection: str) -> list[dict[str, Any]]:
    """A collection's documents without `_id`, by public_id"""
    return list(database_manager.get_collection(collection, database).find({}, {MONGO_ID_KEY: 0},
                                                                          sort=[(PUBLIC_ID_KEY, 1)]))


def _counters(database_manager: MongoDatabaseManager, database: str) -> dict[str, int]:
    """Every counter of a database"""
    return {row[MONGO_ID_KEY]: row[COUNTER_KEY]
            for row in database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database).find({})}


def test_every_document_arrives_under_its_exported_id(database_manager: MongoDatabaseManager,
                                                      databases: tuple[str, str]) -> None:
    """Categories and relations as exported; counts per component in import order"""
    source, target = databases

    imported: dict[str, int] = _import(database_manager, source, target, WriteLedger())

    assert imported == {'section_templates': 1, 'types': 2, 'categories': 1, 'relations': 1}
    assert _stored(database_manager, target, CmdbCategory.COLLECTION) == [CATEGORY]
    assert _stored(database_manager, target, CmdbRelation.COLLECTION) == [RELATION]


def test_a_type_gets_the_default_acl_and_the_importer(database_manager: MongoDatabaseManager,
                                                      databases: tuple[str, str]) -> None:
    """ACL replaced, author and editor rewritten, the rest as exported; a never-edited type keeps no editor"""
    source, target = databases
    _import(database_manager, source, target, WriteLedger())

    router, switch = _stored(database_manager, target, CmdbType.COLLECTION)

    assert router == {**ROUTER, 'acl': AccessControlList.default_json(), 'author_id': IMPORTER_ID,
                      'editor_id': IMPORTER_ID}
    assert switch == {**SWITCH, 'acl': AccessControlList.default_json(), 'author_id': IMPORTER_ID}


def test_counters_are_the_exported_ones(database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
    """Types / categories / relations exactly as exported; templates moved on by the seeded predefined ones"""
    source, target = databases
    _import(database_manager, source, target, WriteLedger())
    predefined: int = len(SectionTemplateCreator().get_predefined_templates())

    counters: dict[str, int] = _counters(database_manager, target)

    for collection in (CmdbType.COLLECTION, CmdbCategory.COLLECTION, CmdbRelation.COLLECTION):
        assert counters[collection] == COUNTERS[collection], collection

    assert counters[CmdbSectionTemplate.COLLECTION] == COUNTERS[CmdbSectionTemplate.COLLECTION] + predefined


def test_the_predefined_templates_are_seeded_above_the_users(database_manager: MongoDatabaseManager,
                                                              databases: tuple[str, str]) -> None:
    """The user's template keeps id 1; the predefined ones come back once each, above the exported counter"""
    source, target = databases
    _import(database_manager, source, target, WriteLedger())
    expected_names: list[str] = [template['name'] for template in SectionTemplateCreator().get_predefined_templates()]

    templates: list[dict[str, Any]] = _stored(database_manager, target, CmdbSectionTemplate.COLLECTION)
    predefined: list[dict[str, Any]] = [template for template in templates if template.get('predefined') is True]

    assert templates[0] == TEMPLATE
    assert sorted(template['name'] for template in predefined) == sorted(expected_names)
    assert all(template[PUBLIC_ID_KEY] > COUNTERS[CmdbSectionTemplate.COLLECTION] for template in predefined)


def test_the_user_settings_are_cleared(database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
    """Settings written between reset and import name the old types"""
    source, target = databases
    _import(database_manager, source, target, WriteLedger())

    assert not _stored(database_manager, target, CmdbUserSetting.COLLECTION)


def test_a_failure_midway_is_undone_completely(database_manager: MongoDatabaseManager, databases: tuple[str, str],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """The relations fail to insert: the undo leaves the target exactly as the reset left it"""
    source, target = databases
    collections: list[str] = [CmdbSectionTemplate.COLLECTION, CmdbType.COLLECTION, CmdbCategory.COLLECTION,
                              CmdbRelation.COLLECTION, CmdbUserSetting.COLLECTION]
    before: dict[str, list[dict[str, Any]]] = {name: _stored(database_manager, target, name) for name in collections}
    counters_before: dict[str, int] = _counters(database_manager, target)
    original = BaseManager.insert_many

    def _failing_on_relations(self, data: list[dict[str, Any]], skip_public: bool = False) -> list[int]:
        if self.collection == CmdbRelation.COLLECTION:
            raise RuntimeError('relations unavailable')

        return original(self, data, skip_public)

    monkeypatch.setattr(BaseManager, 'insert_many', _failing_on_relations)
    ledger: WriteLedger = WriteLedger()

    with pytest.raises(RuntimeError):
        _import(database_manager, source, target, ledger)

    monkeypatch.undo()

    assert not ledger.undo()
    assert {name: _stored(database_manager, target, name) for name in collections} == before
    assert {name: value for name, value in _counters(database_manager, target).items()
            if name in counters_before or value} == counters_before
