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
Functional tests: a section template's name is held once, through the real REST app

  - a create whose name read misses a template stored meanwhile (a lost race) is refused by the index with the same
    400 as the read's, and stores nothing; any other insert failure keeps its own 400
  - a create of a free name works as before
  - deleting a global template leaves a type that claims another template untouched
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.section_templates_manager import SectionTemplatesManagerInsertError
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_templates_constants import (
    TEMPLATE_NAME_TAKEN_MESSAGE,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates/'
TAKEN_NAME: str = 'func-sectpl-unique-taken'
FREE_NAME: str = 'func-sectpl-unique-free'
OTHER_NAME: str = 'func-sectpl-unique-other'
TYPE_ID: int = 93501
OWN_FIELD: str = 'own'
OTHER_FIELD: str = 'unique-other-field'
NAME_KEY: str = SectionTemplateKey.NAME.value
ALL_NAMES: list[str] = [TAKEN_NAME, FREE_NAME, OTHER_NAME]
# MongoDB's own index on _id - created with the collection, never dropped
MONGO_ID_INDEX: str = '_id_'


def _field(name: str) -> dict[str, Any]:
    """A text field definition"""
    return {'type': 'text', 'name': name, 'label': name}


def _create_body(name: str) -> dict[str, str]:
    """POST /section_templates/ parameters for a global template"""
    return {NAME_KEY: name, 'label': name, 'type': SectionType.SECTION.value, 'is_global': 'true',
            'predefined': 'false', 'fields': json.dumps([_field(f'{name}-field')])}


@pytest.fixture(name='templates')
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The template collection behind its declared indexes, purged of the test's names and type before and after"""
    collection = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({NAME_KEY: {'$in': ALL_NAMES}})
        types.delete_many({'public_id': TYPE_ID})

    _purge()
    # The session builds no declared index; the name index is what decides a race. Every index built here is dropped
    # again - left behind, one would refuse the documents other modules seed
    had_indexes: set[str] = set(collection.index_information())
    database_manager.create_indexes(CmdbSectionTemplate.COLLECTION, database_name,
                                    CmdbSectionTemplate.get_index_keys())
    yield collection
    _purge()

    for index_name in set(collection.index_information()) - had_indexes - {MONGO_ID_INDEX}:
        collection.drop_index(index_name)


def _miss_the_name_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route's name read finds nothing - as when a concurrent create has not stored the name yet"""
    monkeypatch.setattr(SectionTemplatesManager, 'get_section_template_by_name', lambda *_args: None)


def test_a_create_that_loses_the_race_gets_the_reads_400(rest_api, templates: Any,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Refused by the index, the same message, nothing stored"""
    assert rest_api.post(ROUTE_URL, query_string=_create_body(TAKEN_NAME)).status_code == HTTPStatus.OK
    _miss_the_name_read(monkeypatch)

    response = rest_api.post(ROUTE_URL, query_string=_create_body(TAKEN_NAME))

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, TEMPLATE_NAME_TAKEN_MESSAGE.format(name=TAKEN_NAME))
    assert templates.count_documents({NAME_KEY: TAKEN_NAME}) == 1


@pytest.mark.usefixtures('templates')
def test_the_read_still_refuses_a_taken_name(rest_api) -> None:
    """The ordinary case, before the index is reached"""
    rest_api.post(ROUTE_URL, query_string=_create_body(TAKEN_NAME))

    response = rest_api.post(ROUTE_URL, query_string=_create_body(TAKEN_NAME))

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, TEMPLATE_NAME_TAKEN_MESSAGE.format(name=TAKEN_NAME))


def test_another_insert_failure_keeps_its_own_400(rest_api, templates: Any,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Not reported as a taken name"""
    def _failing_insert(*_args: Any, **_kwargs: Any) -> int:
        raise SectionTemplatesManagerInsertError('down')

    monkeypatch.setattr(SectionTemplatesManager, 'insert_section_template', _failing_insert)

    response = rest_api.post(ROUTE_URL, query_string=_create_body(FREE_NAME))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] != TEMPLATE_NAME_TAKEN_MESSAGE.format(name=FREE_NAME)
    assert not templates.count_documents({NAME_KEY: FREE_NAME})


def test_a_free_name_is_created(rest_api, templates: Any) -> None:
    """One template stored"""
    response = rest_api.post(ROUTE_URL, query_string=_create_body(FREE_NAME))

    assert response.status_code == HTTPStatus.OK
    assert templates.count_documents({NAME_KEY: FREE_NAME}) == 1


def test_deleting_a_template_leaves_a_type_claiming_another(rest_api, templates: Any,
                                                            database_manager: MongoDatabaseManager,
                                                            database_name: str) -> None:
    """The cleanup is keyed on the deleted template's own name"""
    rest_api.post(ROUTE_URL, query_string=_create_body(FREE_NAME))
    deleted_id: int = templates.find_one({NAME_KEY: FREE_NAME})['public_id']
    templates.insert_one({'public_id': deleted_id + 1, NAME_KEY: OTHER_NAME, 'label': OTHER_NAME,
                          'type': SectionType.SECTION.value, 'is_global': True, 'predefined': False,
                          'fields': [_field(OTHER_FIELD)]})
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_one(make_type_doc(
        TYPE_ID, 'func-sectpl-unique-type', fields=[_field(OWN_FIELD), _field(OTHER_FIELD)],
        sections=[{'type': SectionType.SECTION.value, 'name': OWN_FIELD, 'label': 'Own', 'fields': [OWN_FIELD]},
                  {'type': SectionType.SECTION.value, 'name': OTHER_NAME, 'label': 'Other', 'fields': [OTHER_FIELD]}],
        global_template_ids=[OTHER_NAME],
    ))

    response = rest_api.delete(f'{ROUTE_URL}{deleted_id}')

    stored_type: dict[str, Any] = types.find_one({'public_id': TYPE_ID})
    assert response.status_code == HTTPStatus.OK
    assert stored_type['global_template_ids'] == [OTHER_NAME]
    assert [field['name'] for field in stored_type['fields']] == [OWN_FIELD, OTHER_FIELD]
