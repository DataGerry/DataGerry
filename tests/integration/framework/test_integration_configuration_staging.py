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
Integration tests of migrating an older transfer file against a real MongoDB, with the real updaters

What is pinned: a file of an older version comes back in the importing version's shape - the updaters after its
version ran on it (a duplicate relation name renamed, a dead category type id removed, an acl's shape normalised),
its counters kept; the migrated file passes today's checks with the real type rules, the values a system may keep
(a relation name and a field pattern stored before today's rules) included; no staging database is left behind,
also when an updater fails, and an existing database with the drawn name is never touched; and a type's copy of a
real predefined template is brought in line with what the import seeds
"""
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENTS,
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
    build_component_section,
    build_transfer_file,
    migrate_transfer_file,
)
from cmdb.framework.configuration_transfer import configuration_staging as staging
from cmdb.framework.configuration_transfer.configuration_transfer_constants import STAGING_DATABASE_PREFIX
from cmdb.framework.section_templates import SectionTemplateCreator
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import field_patterns_error
from cmdb.interface.rest_api.routes.relation_routes.relation_structure_helper import relation_name_blocker
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_validation import (
    ImportContext,
    find_import_problems,
    reconcile_template_copies,
)
# -------------------------------------------------------------------------------------------------------------------- #

FILE_VERSION: int = 20261002
TARGET_VERSION: int = 20261014
TARGET_SUFFIX: str = '-staging-target'
COUNTERS: dict[str, int] = {'section_templates': 0, 'types': 40, 'categories': 9, 'relations': 6}
MODELSPEC: str = 'dg-modelspec'


def _type(public_id: int, name: str, **extra: Any) -> dict[str, Any]:
    """An old-version type, shaped like the routes store one"""
    return {'public_id': public_id, 'name': name, 'label': name.title(), 'active': True, 'version': '1.0.0',
            'author_id': 1, 'selectable_as_parent': True, 'global_template_ids': [],
            'fields': [{'type': 'text', 'name': f'{name}-host', 'label': 'Host', 'regex': '(?i)^host'}],
            'render_meta': {'icon': 'fa fa-cube', 'externals': [], 'summary': {'fields': []},
                            'sections': [{'type': 'section', 'name': f'{name}-main', 'label': 'Main',
                                          'fields': [f'{name}-host']}]},
            **extra}


def _relation(public_id: int, name: str) -> dict[str, Any]:
    """An old-version relation"""
    return {'public_id': public_id, 'relation_name': name, 'relation_name_parent': 'contains',
            'relation_name_child': 'is part of', 'parent_type_ids': [4], 'child_type_ids': [5],
            'sections': [], 'fields': []}


def _old_file() -> dict[str, Any]:
    """A file of FILE_VERSION carrying what the updaters since then reshape"""
    items: dict[str, list[dict[str, Any]]] = {
        'section_templates': [],
        'types': [_type(4, 'router', acl={'activated': 'true', 'groups': {'includes': {'2': ['READ']}}}),
                  _type(5, 'switch', acl=None)],
        'categories': [{'public_id': 7, 'name': 'network', 'label': 'Network', 'parent': None, 'types': [4, 99],
                        'meta': {'icon': '', 'order': None}}],
        'relations': [_relation(1, 'has part'), _relation(2, 'has part')],
    }

    return build_transfer_file(FILE_VERSION, {name: build_component_section(COUNTERS[name], rows)
                                              for name, rows in items.items()})


def _items(transfer_file: dict[str, Any], name: TransferComponentName) -> list[dict[str, Any]]:
    """A component's entries"""
    return transfer_file[TransferFileKey.COMPONENTS.value][name.value][TransferSectionKey.ITEMS.value]


def _staging_databases(database_manager: MongoDatabaseManager) -> set[str]:
    """Every database carrying the staging prefix"""
    return {name for name in database_manager.connector.client.list_database_names()
            if name.startswith(STAGING_DATABASE_PREFIX)}


@pytest.fixture(name='target')
def fixture_target(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """An empty target database for the checks, dropped afterwards"""
    target: str = f'{database_name}{TARGET_SUFFIX}'
    database_manager.connector.client.drop_database(target)

    yield target

    database_manager.connector.client.drop_database(target)


def _context(database_manager: MongoDatabaseManager, target: str) -> ImportContext:
    """The target as the checks see it, seeding the real predefined templates"""
    return ImportContext(types_manager=TypesManager(database_manager, target), ipam_locked=False,
                         predefined_templates=tuple(SectionTemplateCreator().get_predefined_templates()))


def test_an_older_file_comes_back_in_the_importing_shape(database_manager: MongoDatabaseManager) -> None:
    """The updaters since its version ran: duplicate renamed, dead id gone, acls normalised; counters kept"""
    migrated: dict[str, Any] = migrate_transfer_file(database_manager, _old_file(), TARGET_VERSION,
                                                     TRANSFER_COMPONENTS)

    assert migrated[TransferFileKey.DB_VERSION.value] == TARGET_VERSION
    assert [relation['relation_name'] for relation in _items(migrated, TransferComponentName.RELATIONS)] == \
        ['has part', 'has part-2']
    assert _items(migrated, TransferComponentName.CATEGORIES)[0]['types'] == [4]
    assert [entry['acl'] for entry in _items(migrated, TransferComponentName.TYPES)] == [
        {'activated': True, 'groups': {'includes': {'2': ['READ']}}},
        {'activated': False, 'groups': {'includes': {}}},
    ]
    assert {name: section[TransferSectionKey.COUNTER.value]
            for name, section in migrated[TransferFileKey.COMPONENTS.value].items()} == COUNTERS


def test_the_migrated_file_passes_todays_checks(database_manager: MongoDatabaseManager, target: str) -> None:
    """Real type rules; a name and a pattern stored before today's rules are kept, as an unchanged save keeps them"""
    migrated: dict[str, Any] = migrate_transfer_file(database_manager, _old_file(), TARGET_VERSION,
                                                     TRANSFER_COMPONENTS)

    assert not find_import_problems(migrated, TARGET_VERSION, _context(database_manager, target))
    # ... which today's create rules would refuse: the point of judging an unchanged save
    router: dict[str, Any] = _items(migrated, TransferComponentName.TYPES)[0]
    assert field_patterns_error(router['fields']) is not None
    assert relation_name_blocker(_items(migrated, TransferComponentName.RELATIONS)[0]['relation_name']) is not None


def test_no_staging_database_is_left_behind(database_manager: MongoDatabaseManager) -> None:
    """After a migration the set of staging databases is what it was"""
    before: set[str] = _staging_databases(database_manager)

    migrate_transfer_file(database_manager, _old_file(), TARGET_VERSION, TRANSFER_COMPONENTS)

    assert _staging_databases(database_manager) == before


def test_a_failing_updater_leaves_no_staging_database(database_manager: MongoDatabaseManager,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """The updater's error surfaces; the staging database is dropped all the same"""
    before: set[str] = _staging_databases(database_manager)

    class _Failing:
        """An updater that fails on start"""
        def __init__(self, *args: Any) -> None:
            pass

        def start_update(self) -> None:
            """Fails"""
            raise RuntimeError('updater failed')

    monkeypatch.setattr(staging, 'load_class', lambda path: _Failing)

    with pytest.raises(RuntimeError):
        migrate_transfer_file(database_manager, _old_file(), TARGET_VERSION, TRANSFER_COMPONENTS)

    assert _staging_databases(database_manager) == before


def test_an_existing_database_with_the_drawn_name_is_never_touched(database_manager: MongoDatabaseManager,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The first draw names an existing database: a second name is drawn, the existing one keeps its data"""
    taken: str = f'{STAGING_DATABASE_PREFIX}{"c" * 32}'
    client = database_manager.connector.client
    client[taken]['keep'].insert_one({'kept': True})
    draws = iter([SimpleNamespace(hex='c' * 32), SimpleNamespace(hex='d' * 32)])
    monkeypatch.setattr(staging, 'uuid4', lambda: next(draws))

    try:
        migrate_transfer_file(database_manager, _old_file(), TARGET_VERSION, TRANSFER_COMPONENTS)

        assert client[taken]['keep'].count_documents({'kept': True}) == 1
        assert f'{STAGING_DATABASE_PREFIX}{"d" * 32}' not in client.list_database_names()
    finally:
        client.drop_database(taken)


def test_a_copy_of_a_real_predefined_template_is_reconciled(database_manager: MongoDatabaseManager,
                                                            target: str) -> None:
    """A type carrying an outdated copy of dg-modelspec gets today's section and field definitions"""
    seeded: dict[str, Any] = next(template for template in SectionTemplateCreator().get_predefined_templates()
                                  if template['name'] == MODELSPEC)
    outdated: dict[str, Any] = _type(
        8, 'server', global_template_ids=[MODELSPEC],
        fields=[{'type': 'text', 'name': 'dg-modelspec-manufacturer', 'label': 'Old label'}],
        render_meta={'icon': '', 'externals': [], 'summary': {'fields': []},
                     'sections': [{'type': 'section', 'name': MODELSPEC, 'label': 'Old',
                                   'fields': ['dg-modelspec-manufacturer']}]},
    )
    transfer_file: dict[str, Any] = build_transfer_file(TARGET_VERSION, {
        'section_templates': build_component_section(0, []),
        'types': build_component_section(8, [deepcopy(outdated)]),
        'categories': build_component_section(0, []),
        'relations': build_component_section(0, []),
    })

    assert not reconcile_template_copies(transfer_file, _context(database_manager, target))

    server: dict[str, Any] = _items(transfer_file, TransferComponentName.TYPES)[0]
    section: dict[str, Any] = server['render_meta']['sections'][0]
    assert section['fields'] == [field['name'] for field in seeded['fields']]
    assert [field for field in server['fields'] if field['name'].startswith(MODELSPEC)] == seeded['fields']
