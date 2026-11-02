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
Integration tests for cmdb.database.updater.versions.updater_20261029 against a real MongoDB

Seeds section templates sharing one name, one whose renamed form is already taken, a near-twin in another case, a
second name whose holder is predefined but has the higher id, and a type claiming the first name - with the unique
index dropped, as on a database the rule has not reached yet; runs the migration and asserts:
  - the lowest public_id keeps the name, a predefined template keeps it over a lower id; the others are renamed
    ``<name>-<public_id>`` (again when taken); the near-twin is left alone; nothing but the name changes
  - the rename is logged with the claiming type's id, and the type is not written
  - the unique index is in place afterwards and refuses a duplicate
  - a second run changes nothing
"""
import logging
from typing import Any, Iterator

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions import updater_20261029 as module
from cmdb.database.updater.versions.updater_20261029 import Update20261029
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

NAME: str = SectionTemplateKey.NAME.value
PUBLIC_ID: str = SectionTemplateKey.PUBLIC_ID.value
PREDEFINED: str = SectionTemplateKey.PREDEFINED.value
LABEL: str = SectionTemplateKey.LABEL.value
KEEPER_ID: int = 98801
SECOND_ID: int = 98802
THIRD_ID: int = 98803
TAKEN_ID: int = 98804
TWIN_ID: int = 98805
USER_ID: int = 98806
PREDEFINED_ID: int = 98807
CLAIMING_TYPE_ID: int = 98811
SHARED: str = 'upd-tpl-network'
SEEDED_PREDEFINED: str = 'upd-tpl-predefined'
SEEDED: dict[int, tuple[str, bool]] = {
    THIRD_ID: (SHARED, False), KEEPER_ID: (SHARED, False), SECOND_ID: (SHARED, False),
    TAKEN_ID: (f'{SHARED}-{SECOND_ID}', False), TWIN_ID: (SHARED.upper(), False),
    USER_ID: (SEEDED_PREDEFINED, False), PREDEFINED_ID: (SEEDED_PREDEFINED, True),
}
EXPECTED: dict[int, str] = {
    KEEPER_ID: SHARED, SECOND_ID: f'{SHARED}-{SECOND_ID}-{SECOND_ID}', THIRD_ID: f'{SHARED}-{THIRD_ID}',
    TAKEN_ID: f'{SHARED}-{SECOND_ID}', TWIN_ID: SHARED.upper(),
    USER_ID: f'{SEEDED_PREDEFINED}-{USER_ID}', PREDEFINED_ID: SEEDED_PREDEFINED,
}


@pytest.fixture(name='templates')
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The template collection without its unique name index, holding the seeded duplicates and a claiming type"""
    collection = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    collection.delete_many({PUBLIC_ID: {'$in': list(SEEDED)}})
    types.delete_many({PUBLIC_ID: CLAIMING_TYPE_ID})

    had_index: bool = NAME in collection.index_information()

    if had_index:
        collection.drop_index(NAME)

    collection.insert_many([{PUBLIC_ID: public_id, NAME: name, PREDEFINED: predefined, LABEL: f'kept-{public_id}'}
                            for public_id, (name, predefined) in SEEDED.items()])
    types.insert_one({PUBLIC_ID: CLAIMING_TYPE_ID, NAME: 'upd-tpl-type',
                      TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: [SHARED]})
    yield collection
    collection.delete_many({PUBLIC_ID: {'$in': list(SEEDED)}})
    types.delete_many({PUBLIC_ID: CLAIMING_TYPE_ID})

    # Leave the index as the session had it: the run built it
    if not had_index and NAME in collection.index_information():
        collection.drop_index(NAME)


def _names(templates: Any) -> dict[int, Any]:
    """The seeded templates' names by public_id."""
    return {row[PUBLIC_ID]: row[NAME] for row in templates.find({PUBLIC_ID: {'$in': list(SEEDED)}})}


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration."""
    Update20261029(database_manager, database_name).start_update()


def test_the_duplicates_are_renamed_and_the_rest_left(database_manager, database_name, templates) -> None:
    """Only the name changes; a predefined template keeps its name over a lower id"""
    _run(database_manager, database_name)

    assert _names(templates) == EXPECTED
    assert {row[PUBLIC_ID]: row[LABEL] for row in templates.find({PUBLIC_ID: {'$in': list(SEEDED)}})} == {
        public_id: f'kept-{public_id}' for public_id in SEEDED}


@pytest.mark.usefixtures('templates')
def test_the_rename_names_the_claiming_type_and_leaves_it(database_manager, database_name,
                                                          caplog: pytest.LogCaptureFixture) -> None:
    """The type still claims the kept name"""
    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        _run(database_manager, database_name)

    shared_renames: list[str] = [record.getMessage() for record in caplog.records
                                 if f'{SHARED}-{THIRD_ID}' in record.getMessage()]
    stored_type: dict[str, Any] = database_manager.get_collection(CmdbType.COLLECTION, database_name).find_one(
        {PUBLIC_ID: CLAIMING_TYPE_ID})
    assert shared_renames and str([CLAIMING_TYPE_ID]) in shared_renames[0]
    assert stored_type[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] == [SHARED]


def test_the_unique_index_is_built_and_refuses_a_duplicate(database_manager, database_name, templates) -> None:
    """The guarantee the create route relies on"""
    _run(database_manager, database_name)

    assert templates.index_information()[NAME].get('unique') is True
    with pytest.raises(DuplicateKeyError):
        templates.insert_one({PUBLIC_ID: PREDEFINED_ID + 1, NAME: SHARED})


def test_a_second_run_changes_nothing(database_manager, database_name, templates) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    _run(database_manager, database_name)

    assert _names(templates) == EXPECTED
