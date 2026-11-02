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
Integration tests of the import checks against a real MongoDB, with the real type create rules

A configuration is seeded into one scratch database and exported through the real components; the file is judged
against a second, empty scratch database through a real TypesManager. What is pinned: an export of a coherent
configuration passes on an empty system - a reference section into another type of the file included, the ACL not
judged; the real create rules answer through the checks (a name already stored on the target, a licence-gated
special type and a port-bearing type on an unlicensed target); and an entry hand-edited into an incoherent file is
named by component and entry. The context asks the stored types the way `build_import_context` does - one projected
read (`StoredTypeNames`) - and a judgement of 1 or of 200 type entries reads `framework.types` exactly once, on an
empty target and on one where every name is taken, the clashes still named
"""
from collections import Counter
from copy import deepcopy
from typing import Any, Iterator
from unittest.mock import patch

import pymongo.collection
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CategoriesManager, SectionTemplatesManager, TypesManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.framework.configuration_transfer import (
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
    TypeComponent,
    export_configuration,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_validation import (
    ImportContext,
    StoredTypeNames,
    find_import_problems,
    type_problems,
)
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

SOURCE_SUFFIX: str = '-import-checks-source'
TARGET_SUFFIX: str = '-import-checks-target'
DB_VERSION: int = 20261014
ROUTER_ID: int = 4
SERVER_ID: int = 9


def _type(public_id: int, name: str, sections: list[dict[str, Any]], fields: list[dict[str, Any]],
          **extra: Any) -> dict[str, Any]:
    """A stored type, shaped like the type routes store one"""
    return {'public_id': public_id, 'name': name, 'label': name.title(), 'active': True, 'version': '1.0.0',
            'author_id': 1, 'selectable_as_parent': True, 'global_template_ids': [], 'fields': fields,
            'render_meta': {'icon': 'fa fa-cube', 'sections': sections, 'externals': [], 'summary': {'fields': []}},
            'acl': {'activated': True, 'groups': {'includes': {'2': ['READ']}}}, **extra}


ROUTER: dict[str, Any] = _type(
    ROUTER_ID, 'router',
    sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}],
    fields=[{'type': 'text', 'name': 'host', 'label': 'Host'}],
)
SERVER: dict[str, Any] = _type(
    SERVER_ID, 'server',
    sections=[{'type': 'ref-section', 'name': 'uplink', 'label': 'Uplink', 'fields': [],
               'reference': {'type_id': ROUTER_ID, 'section_name': 'main', 'selected_fields': ['host']}}],
    fields=[{'type': 'ref-section-field', 'name': 'uplink-field', 'label': 'Uplink'}],
)
TEMPLATE: dict[str, Any] = {'public_id': 3, 'name': 'user-template', 'label': 'User Template', 'is_global': False,
                            'predefined': False, 'type': 'section',
                            'fields': [{'name': 'serial', 'label': 'Serial', 'type': 'text'}]}
PREDEFINED: dict[str, Any] = {'public_id': 1, 'name': 'dg-seeded', 'label': 'Seeded', 'predefined': True,
                              'type': 'section', 'fields': []}
CATEGORY: dict[str, Any] = {'public_id': 7, 'name': 'network', 'label': 'Network', 'parent': None,
                            'types': [ROUTER_ID, SERVER_ID], 'meta': {'icon': '', 'order': None}}
RELATION: dict[str, Any] = {'public_id': 2, 'relation_name': 'uplink', 'relation_name_parent': 'serves',
                            'relation_name_child': 'is served by', 'parent_type_ids': [ROUTER_ID],
                            'child_type_ids': [SERVER_ID], 'sections': [], 'fields': []}


@pytest.fixture(name='databases')
def fixture_databases(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, str]]:
    """A seeded source and an empty target, both dropped afterwards"""
    source, target = f'{database_name}{SOURCE_SUFFIX}', f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client

    for name in (source, target):
        client.drop_database(name)

    for collection, rows in ((CmdbType.COLLECTION, [ROUTER, SERVER]),
                             (CmdbSectionTemplate.COLLECTION, [TEMPLATE, PREDEFINED]),
                             (CmdbCategory.COLLECTION, [CATEGORY]),
                             (CmdbRelation.COLLECTION, [RELATION])):
        client[source][collection].insert_many(deepcopy(rows))

    yield source, target

    for name in (source, target):
        client.drop_database(name)


def _exported(database_manager: MongoDatabaseManager, source: str) -> dict[str, Any]:
    """The source's export through the real components"""
    return export_configuration([
        SectionTemplateComponent(SectionTemplatesManager(database_manager, source)),
        TypeComponent(TypesManager(database_manager, source)),
        CategoryComponent(CategoriesManager(database_manager, source)),
        RelationComponent(RelationsManager(database_manager, source)),
    ], DB_VERSION, EXPORT_NAME)


def _context(database_manager: MongoDatabaseManager, target: str, ipam_locked: bool = False) -> ImportContext:
    """The target as the checks see it - its stored types read once, as build_import_context reads them"""
    types_manager: TypesManager = TypesManager(database_manager, target)

    return ImportContext(types_manager=types_manager, ipam_locked=ipam_locked,
                         predefined_templates=(deepcopy(PREDEFINED),), stored_types=StoredTypeNames.read(types_manager))


def _types(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The file's type entries"""
    return data[TransferFileKey.COMPONENTS.value][TransferComponentName.TYPES.value][TransferSectionKey.ITEMS.value]


def test_a_coherent_export_passes_on_an_empty_system(database_manager: MongoDatabaseManager,
                                                     databases: tuple[str, str]) -> None:
    """Reference section, category, relation, a user template - nothing to report; the ACL is not judged"""
    source, target = databases

    assert not find_import_problems(_exported(database_manager, source), DB_VERSION,
                                    _context(database_manager, target))


def test_a_name_stored_on_the_target_is_refused(database_manager: MongoDatabaseManager,
                                                databases: tuple[str, str]) -> None:
    """The real create rules read the target's types"""
    source, target = databases
    database_manager.get_collection(CmdbType.COLLECTION, target).insert_one({'public_id': 50, 'name': 'router'})

    problems: list[str] = find_import_problems(_exported(database_manager, source), DB_VERSION,
                                               _context(database_manager, target))

    assert len(problems) == 1 and problems[0].startswith(f'types {ROUTER_ID}: ')


@pytest.mark.parametrize('flag', [{'special_type': 'RACK'}, {'uses_ports': True}])
def test_a_licence_gated_type_is_refused_on_an_unlicensed_target(database_manager: MongoDatabaseManager,
                                                                 databases: tuple[str, str],
                                                                 flag: dict[str, Any]) -> None:
    """A gated special type or a port-bearing type, IPAM locked -> refused; licensed -> passes"""
    source, target = databases
    data: dict[str, Any] = _exported(database_manager, source)
    _types(data)[0].update(flag)

    locked: list[str] = find_import_problems(data, DB_VERSION, _context(database_manager, target, ipam_locked=True))

    assert len(locked) == 1 and locked[0].startswith(f'types {ROUTER_ID}: ')
    assert not find_import_problems(data, DB_VERSION, _context(database_manager, target))


def test_a_hand_edited_reference_is_named(database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
    """The router left out of the file: the server's reference section, the category and the relation all say so"""
    source, target = databases
    data: dict[str, Any] = _exported(database_manager, source)
    data[TransferFileKey.COMPONENTS.value][TransferComponentName.TYPES.value][TransferSectionKey.ITEMS.value] = [
        entry for entry in _types(data) if entry['public_id'] != ROUTER_ID
    ]
    # The count is edited along, as a careful hand would - a count left as exported is its own problem
    data[TransferFileKey.INFORMATION.value][TransferInformationKey.COUNTS.value][
        TransferComponentName.TYPES.value] = len(_types(data))

    problems: list[str] = find_import_problems(data, DB_VERSION, _context(database_manager, target))

    assert [problem.split(':')[0] for problem in problems] == [
        f'types {SERVER_ID}', f'categories {CATEGORY["public_id"]}', f'relations {RELATION["public_id"]}',
    ]


# -------------------------------------------------------------------------------------------------------------------- #
#                                  one read of the stored types, whatever the file                                     #
# -------------------------------------------------------------------------------------------------------------------- #
MANY_TYPES: int = 200
GENERATED_TYPE_BASE: int = 300


def _generated_types(count: int) -> list[dict[str, Any]]:
    """`count` plain type entries with their own names"""
    return [_type(GENERATED_TYPE_BASE + i, f'generated-{i}', [], []) for i in range(count)]


def _type_reads(database_manager: MongoDatabaseManager, target: str, items: list[dict[str, Any]]) -> tuple[list, int]:
    """Builds the context and judges the types; answers the problems and the reads of framework.types it cost"""
    counted: Counter = Counter()
    real_find, real_find_one = pymongo.collection.Collection.find, pymongo.collection.Collection.find_one

    def _find(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counted[collection.name] += 1
        return real_find(collection, *args, **kwargs)

    def _find_one(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counted[collection.name] += 1
        return real_find_one(collection, *args, **kwargs)

    with patch.object(pymongo.collection.Collection, 'find', _find), \
            patch.object(pymongo.collection.Collection, 'find_one', _find_one):
        problems: list[str] = type_problems(items, {TransferComponentName.TYPES.value: items},
                                            _context(database_manager, target))

    return problems, counted[CmdbType.COLLECTION]


@pytest.mark.parametrize('count', [1, MANY_TYPES], ids=['one-type', 'two-hundred-types'])
def test_an_empty_target_costs_one_read(database_manager: MongoDatabaseManager, databases: tuple[str, str],
                                        count: int) -> None:
    """What the import sees: nothing stored, nothing refused, one read"""
    _source, target = databases

    problems, reads = _type_reads(database_manager, target, _generated_types(count))

    assert (problems, reads) == ([], 1)


@pytest.mark.parametrize('count', [1, MANY_TYPES], ids=['one-type', 'two-hundred-types'])
def test_a_target_holding_every_name_costs_one_read(database_manager: MongoDatabaseManager,
                                                    databases: tuple[str, str], count: int) -> None:
    """What the preview of a system not yet reset can see: every clash named, still one read"""
    _source, target = databases
    items: list[dict[str, Any]] = _generated_types(count)
    database_manager.get_collection(CmdbType.COLLECTION, target).insert_many(deepcopy(items))

    problems, reads = _type_reads(database_manager, target, items)

    assert reads == 1
    assert len(problems) == count and all('already exists' in problem for problem in problems)
