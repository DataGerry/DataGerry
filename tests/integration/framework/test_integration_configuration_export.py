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
Integration tests of the configuration export against a real MongoDB, through the real managers

On a scratch database of its own: each component exports its own collection's documents as stored - in ascending
public_id order whatever the insert order, without `_id`, the predefined section templates left out - and its
counter as stored (above the highest id when ids were handed out and deleted, 0 without a counter); the version is
read from the updater section; and a datetime survives the JSON round trip the file goes through. The file's
`information` counts what was exported - the predefined templates left out of the count too - and its empty `meta`
names every exported category
"""
import json
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.database.json_codec import default, object_hook
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.manager import CategoriesManager, SectionTemplatesManager, SettingsManager, TypesManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENT_NAMES,
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
    TypeComponent,
    build_empty_meta,
    export_configuration,
    find_transfer_file_problems,
    read_database_version,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

SCRATCH_SUFFIX: str = '-configuration-export'
PUBLIC_ID_KEY: str = 'public_id'
MONGO_ID_KEY: str = '_id'
COUNTER_KEY: str = 'counter'
NAME_KEY: str = 'name'
PREDEFINED_KEY: str = SectionTemplateKey.PREDEFINED.value

DB_VERSION: int = 20261014
TYPES_COUNTER: int = 30
CATEGORIES_COUNTER: int = 8
TEMPLATES_COUNTER: int = 12
CREATED: datetime = datetime(2026, 10, 12, 9, 30, 15, 123000)

TYPES: list[dict[str, Any]] = [
    {PUBLIC_ID_KEY: 21, NAME_KEY: 'router', 'creation_time': CREATED},
    {PUBLIC_ID_KEY: 4, NAME_KEY: 'switch', 'creation_time': CREATED},
]
CATEGORIES: list[dict[str, Any]] = [{PUBLIC_ID_KEY: 7, NAME_KEY: 'network', 'types': [4, 21]}]
TEMPLATES: list[dict[str, Any]] = [
    {PUBLIC_ID_KEY: 1, NAME_KEY: 'dg-predefined', PREDEFINED_KEY: True},
    {PUBLIC_ID_KEY: 11, NAME_KEY: 'user-flagged', PREDEFINED_KEY: False},
    {PUBLIC_ID_KEY: 9, NAME_KEY: 'user-unflagged'},
]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """Types, categories and templates with counters, no relations at all, and an updater version"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    database = client[scratch]

    database[CmdbType.COLLECTION].insert_many([dict(row) for row in TYPES])
    database[CmdbCategory.COLLECTION].insert_many([dict(row) for row in CATEGORIES])
    database[CmdbSectionTemplate.COLLECTION].insert_many([dict(row) for row in TEMPLATES])
    database[PUBLIC_ID_COUNTER_COLLECTION].insert_many([
        {MONGO_ID_KEY: CmdbType.COLLECTION, COUNTER_KEY: TYPES_COUNTER},
        {MONGO_ID_KEY: CmdbCategory.COLLECTION, COUNTER_KEY: CATEGORIES_COUNTER},
        {MONGO_ID_KEY: CmdbSectionTemplate.COLLECTION, COUNTER_KEY: TEMPLATES_COUNTER},
    ])
    SettingsManager(database_manager, scratch).write(
        UpdaterSetting.SECTION.value, {UpdaterSetting.VERSION.value: DB_VERSION},
    )

    yield scratch

    client.drop_database(scratch)


def _export_file(database_manager: MongoDatabaseManager, scratch: str) -> dict[str, Any]:
    """The whole transfer file of the scratch database, through the real managers"""
    components = [
        SectionTemplateComponent(SectionTemplatesManager(database_manager, scratch)),
        TypeComponent(TypesManager(database_manager, scratch)),
        CategoryComponent(CategoriesManager(database_manager, scratch)),
        RelationComponent(RelationsManager(database_manager, scratch)),
    ]

    return export_configuration(components, DB_VERSION, EXPORT_NAME)


def _export(database_manager: MongoDatabaseManager, scratch: str) -> dict[str, Any]:
    """The exported components of the scratch database"""
    return _export_file(database_manager, scratch)[TransferFileKey.COMPONENTS.value]


def _section(exported: dict[str, Any], name: str) -> tuple[int, list[dict[str, Any]]]:
    """A section's counter and items"""
    return exported[name][TransferSectionKey.COUNTER.value], exported[name][TransferSectionKey.ITEMS.value]


def test_types_are_exported_as_stored_in_ascending_order(database_manager: MongoDatabaseManager,
                                                         scratch: str) -> None:
    """Every key as stored, no `_id`, sorted by public_id; the counter as stored"""
    counter, items = _section(_export(database_manager, scratch), TypeComponent.NAME.value)

    assert counter == TYPES_COUNTER
    assert items == sorted(TYPES, key=lambda row: row[PUBLIC_ID_KEY])


def test_only_the_users_section_templates_are_exported(database_manager: MongoDatabaseManager,
                                                       scratch: str) -> None:
    """Predefined left out; flagged False and unflagged both exported"""
    counter, items = _section(_export(database_manager, scratch), SectionTemplateComponent.NAME.value)

    assert counter == TEMPLATES_COUNTER
    assert [item[PUBLIC_ID_KEY] for item in items] == [9, 11]


def test_categories_keep_their_type_ids(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The type references travel as stored"""
    counter, items = _section(_export(database_manager, scratch), CategoryComponent.NAME.value)

    assert (counter, items) == (CATEGORIES_COUNTER, CATEGORIES)


def test_a_component_without_documents_or_counter_is_an_empty_section(database_manager: MongoDatabaseManager,
                                                                      scratch: str) -> None:
    """No relation and no relation counter -> counter 0, no items"""
    assert _section(_export(database_manager, scratch), RelationComponent.NAME.value) == (0, [])


def test_the_version_is_read_from_the_updater_section(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The recorded version, as written"""
    assert read_database_version(SettingsManager(database_manager, scratch)) == DB_VERSION


def test_a_database_without_a_version_has_none(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """No updater section -> None, never a fallback"""
    SettingsManager(database_manager, scratch).delete_section(UpdaterSetting.SECTION.value)

    assert read_database_version(SettingsManager(database_manager, scratch)) is None


def test_a_datetime_survives_the_files_json_round_trip(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Encoded with the export's hook, decoded with the codec's: the same instant comes back, as aware UTC"""
    exported: dict[str, Any] = _export(database_manager, scratch)

    decoded: dict[str, Any] = json.loads(json.dumps(exported, default=default), object_hook=object_hook)

    assert decoded[TypeComponent.NAME.value][TransferSectionKey.ITEMS.value][0]['creation_time'] == \
        CREATED.replace(tzinfo=timezone.utc)


def test_the_information_counts_what_was_exported(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Two types, one category, the two user templates - not the predefined one - and no relation"""
    transfer_file: dict[str, Any] = _export_file(database_manager, scratch)

    assert transfer_file[TransferFileKey.INFORMATION.value][TransferInformationKey.COUNTS.value] == {
        SectionTemplateComponent.NAME.value: 2,
        TypeComponent.NAME.value: len(TYPES),
        CategoryComponent.NAME.value: len(CATEGORIES),
        RelationComponent.NAME.value: 0,
    }


def test_the_meta_names_every_exported_category(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Empty, ready to be filled in for a best-practice model"""
    transfer_file: dict[str, Any] = _export_file(database_manager, scratch)

    assert transfer_file[TransferFileKey.META.value] == build_empty_meta([row[NAME_KEY] for row in CATEGORIES])


def test_the_exported_file_passes_the_imports_check(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Its envelope and both sections - after the JSON round trip it goes through"""
    transfer_file: dict[str, Any] = json.loads(json.dumps(_export_file(database_manager, scratch), default=default),
                                               object_hook=object_hook)

    assert not find_transfer_file_problems(transfer_file, TRANSFER_COMPONENT_NAMES)
