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
Integration tests for the narrowed small managers against a real MongoDB

What the unit tier stubs, run end-to-end:

- ``SectionTemplatesManager`` on GenericManager: the inserted document holds exactly the model's keys, the reads
  answer models, the by-name read and the uncounted read find what was stored, an update and a delete reach the
  document - and a stored template the model cannot read is the read's typed error, not a crash
- ``LogsManager.iterate``: a stored log CmdbObjectLog cannot read is the typed iteration error
- ``ExtendableOptionsManager.get_option_values``: the projected read still answers the values in creation order
- ``DocapiTemplatesManager.get_template_by_name``: a stored template without its name is the typed GetError
- a real database refusal (an unknown query operator) is each read's typed error
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.logs_manager import LogsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import SectionType
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.docapi_templates_manager import DocapiTemplatesManagerGetError
from cmdb.errors.manager.extendable_options_manager import ExtendableOptionsManagerGetError
from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerGetError,
    SectionTemplatesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_ID: int = 97301
SECOND_TEMPLATE_ID: int = 97302
TEMPLATE_NAME: str = 'it-small-narrowing'
SECOND_TEMPLATE_NAME: str = 'it-small-narrowing-2'
UNREADABLE_TEMPLATE_NAME: str = 'it-small-narrowing-unreadable'
CHANGED_LABEL: str = 'Changed'
# A marker only these tests' templates carry, so the uncounted read is scoped to them
MARKER_KEY: str = 'type'
MARKER_VALUE: str = 'it-small-narrowing-marker'

LOG_OBJECT_ID: int = 97311
DOCAPI_TEMPLATE_ID: int = 97321
# A query for a null name also matches a document that has no name at all - the one the model refuses
DOCAPI_MISSING_NAME: None = None
OPTION_TYPE: str = 'IT_SMALL_NARROWING'
OPTION_VALUES: list[str] = ['first', 'second']
OPTION_IDS: list[int] = [97331, 97332]

# A query MongoDB itself refuses when it runs it - a real database failure, not a stub
REFUSED_CRITERIA: dict[str, Any] = {'name': {'$no_such_operator': 1}}


def _template(public_id: int, name: str) -> dict[str, Any]:
    """The initialisation data of a non-global section template"""
    return {'public_id': public_id, 'name': name, 'label': name, 'type': SectionType.SECTION.value, 'fields': []}


@pytest.fixture(name='templates')
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str):
    """The section-template collection, emptied of these tests' documents before and after"""
    collection = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    names: list[str] = [TEMPLATE_NAME, SECOND_TEMPLATE_NAME, UNREADABLE_TEMPLATE_NAME]

    collection.delete_many({'name': {'$in': names}})
    yield collection
    collection.delete_many({'name': {'$in': names}})


@pytest.fixture(name='section_templates_manager')
def fixture_section_templates_manager(database_manager: MongoDatabaseManager) -> SectionTemplatesManager:
    """A SectionTemplatesManager on the test database"""
    return SectionTemplatesManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                         SectionTemplatesManager on GenericManager                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_inserted_template_holds_exactly_the_model_keys(section_templates_manager: SectionTemplatesManager,
                                                           templates) -> None:
    """The template is stored through the model: its keys, nothing a caller added beside them"""
    created: int = section_templates_manager.insert_section_template(_template(TEMPLATE_ID, TEMPLATE_NAME))

    stored: dict[str, Any] = templates.find_one({'public_id': created}, {'_id': 0})

    assert created == TEMPLATE_ID
    assert stored == CmdbSectionTemplate.to_json(CmdbSectionTemplate(**_template(TEMPLATE_ID, TEMPLATE_NAME)))


def test_the_reads_answer_the_stored_template(section_templates_manager: SectionTemplatesManager,
                                              templates) -> None:
    """By id, by name and uncounted: each read answers the model of what was stored"""
    del templates
    section_templates_manager.insert_section_template(_template(TEMPLATE_ID, TEMPLATE_NAME))

    by_id = section_templates_manager.get_section_template(TEMPLATE_ID)
    by_name = section_templates_manager.get_section_template_by_name(TEMPLATE_NAME)

    assert isinstance(by_id, CmdbSectionTemplate) and by_id.name == TEMPLATE_NAME
    assert isinstance(by_name, CmdbSectionTemplate) and by_name.public_id == TEMPLATE_ID
    assert section_templates_manager.get_section_template_by_name(SECOND_TEMPLATE_NAME) is None


def test_the_uncounted_read_answers_in_public_id_order(section_templates_manager: SectionTemplatesManager,
                                                       templates) -> None:
    """get_section_templates_by finds the matching templates, ordered by public_id"""
    templates.insert_many([
        {**_template(SECOND_TEMPLATE_ID, SECOND_TEMPLATE_NAME), MARKER_KEY: MARKER_VALUE},
        {**_template(TEMPLATE_ID, TEMPLATE_NAME), MARKER_KEY: MARKER_VALUE},
    ])

    found = section_templates_manager.get_section_templates_by({MARKER_KEY: MARKER_VALUE})

    assert [template.public_id for template in found] == [TEMPLATE_ID, SECOND_TEMPLATE_ID]


def test_an_update_and_a_delete_reach_the_document(section_templates_manager: SectionTemplatesManager,
                                                   templates) -> None:
    """The inherited update writes the new state; the inherited delete removes the document"""
    section_templates_manager.insert_section_template(_template(TEMPLATE_ID, TEMPLATE_NAME))
    changed: dict[str, Any] = {**_template(TEMPLATE_ID, TEMPLATE_NAME), 'label': CHANGED_LABEL}

    section_templates_manager.update_section_template(TEMPLATE_ID, changed)

    assert templates.find_one({'public_id': TEMPLATE_ID})['label'] == CHANGED_LABEL
    assert section_templates_manager.delete_section_template(TEMPLATE_ID) is True
    assert templates.count_documents({'public_id': TEMPLATE_ID}) == 0


def test_an_unreadable_stored_template_is_the_reads_typed_error(section_templates_manager: SectionTemplatesManager,
                                                                templates) -> None:
    """A stored template without a public_id cannot be built: the uncounted read answers its IterationError"""
    templates.insert_one({'name': UNREADABLE_TEMPLATE_NAME, MARKER_KEY: MARKER_VALUE})

    with pytest.raises(SectionTemplatesManagerIterationError) as caught:
        section_templates_manager.get_section_templates_by({MARKER_KEY: MARKER_VALUE})

    assert isinstance(caught.value.args[0], CmdbSectionTemplate.INIT_FROM_DATA_ERROR)


def test_a_refused_query_is_the_reads_typed_error(section_templates_manager: SectionTemplatesManager) -> None:
    """MongoDB refusing the query is the database failure the read wraps - by name and uncounted"""
    with pytest.raises(SectionTemplatesManagerIterationError):
        section_templates_manager.get_section_templates_by(REFUSED_CRITERIA)

    with pytest.raises(SectionTemplatesManagerGetError):
        section_templates_manager.get_section_template_by_name({'$no_such_operator': 1})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                LogsManager.iterate                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='logs')
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The logs collection, emptied of this test's documents before and after"""
    collection = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    collection.delete_many({'object_id': LOG_OBJECT_ID})
    yield collection
    collection.delete_many({'object_id': LOG_OBJECT_ID})


def test_an_unreadable_stored_log_is_the_iteration_error(database_manager: MongoDatabaseManager, logs) -> None:
    """A stored log without a public_id is the read's BaseManagerIterationError, carrying the model's error"""
    logs.insert_one({'object_id': LOG_OBJECT_ID, 'log_type': CmdbObjectLog.__name__})

    with pytest.raises(BaseManagerIterationError) as caught:
        LogsManager(database_manager).iterate(BuilderParameters({'object_id': LOG_OBJECT_ID}))

    assert isinstance(caught.value.args[0], CmdbObjectLog.INIT_FROM_DATA_ERROR)


# -------------------------------------------------------------------------------------------------------------------- #
#                                     ExtendableOptionsManager / DocapiTemplatesManager                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='options')
def fixture_options(database_manager: MongoDatabaseManager, database_name: str):
    """Two options of a type only this test uses, inserted out of creation order; removed afterwards"""
    collection = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)

    collection.delete_many({'option_type': OPTION_TYPE})
    collection.insert_many([
        {'public_id': OPTION_IDS[1], 'value': OPTION_VALUES[1], 'option_type': OPTION_TYPE, 'predefined': False},
        {'public_id': OPTION_IDS[0], 'value': OPTION_VALUES[0], 'option_type': OPTION_TYPE, 'predefined': False},
    ])
    yield collection
    collection.delete_many({'option_type': OPTION_TYPE})


def test_the_projected_option_read_answers_the_values_in_creation_order(database_manager: MongoDatabaseManager,
                                                                        options) -> None:
    """Only the value is read, and the values come back ordered by public_id"""
    del options

    assert ExtendableOptionsManager(database_manager).get_option_values(OPTION_TYPE) == OPTION_VALUES


def test_a_refused_option_query_is_the_get_error(database_manager: MongoDatabaseManager) -> None:
    """MongoDB refusing the query is the typed GetError"""
    with pytest.raises(ExtendableOptionsManagerGetError):
        ExtendableOptionsManager(database_manager).get_option_values({'$no_such_operator': 1})


@pytest.fixture(name='docapi_templates')
def fixture_docapi_templates(database_manager: MongoDatabaseManager, database_name: str):
    """The docapi-template collection, emptied of this test's document before and after"""
    collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)

    collection.delete_many({'public_id': DOCAPI_TEMPLATE_ID})
    yield collection
    collection.delete_many({'public_id': DOCAPI_TEMPLATE_ID})


def test_an_unreadable_docapi_template_is_the_get_error(database_manager: MongoDatabaseManager,
                                                        docapi_templates) -> None:
    """A stored template without its required name cannot be built: the by-name read answers its GetError"""
    docapi_templates.insert_one({'public_id': DOCAPI_TEMPLATE_ID})

    with pytest.raises(DocapiTemplatesManagerGetError) as caught:
        DocapiTemplatesManager(database_manager).get_template_by_name(DOCAPI_MISSING_NAME)

    assert isinstance(caught.value.args[0], DocapiTemplate.INIT_FROM_DATA_ERROR)
