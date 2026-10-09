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
Integration tests for DocapiTemplate on CmdbDAO, against a real MongoDB

  - the two indexes the model declares (unique name, unique public_id) build on the collection - the test
    session does not run the CollectionValidator, so the fixture builds them from `get_index_keys()`
  - a body the write schemas accept, built into the model and stored, reads back as a document that satisfies
    the model's own schema - also an old document missing optional keys - and the same update twice stores the
    same document
  - `DocapiTemplatesManager` stores and reads a template through the shared from_data / to_json: a stored
    document without `active` reads as active, an id sent as text is stored as an integer, and inserting a
    second template of the same name fails on the name index rather than storing a duplicate
"""
from typing import Any

import pytest
from cerberus import Validator  # type: ignore

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager import DocapiTemplatesManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_routes import (
    DOCAPI_TEMPLATE_CREATE_SCHEMA,
    DOCAPI_TEMPLATE_UPDATE_SCHEMA,
)

from cmdb.errors.manager.docapi_templates_manager import DocapiTemplatesManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_ID: int = 80661
TEXT_ID_TEMPLATE_ID: int = 80662
SEEDED_IDS: list[int] = [TEMPLATE_ID, TEXT_ID_TEMPLATE_ID]
NAME_PREFIX: str = 'tpl-integration-'

# The index names DocapiTemplate declares, and CmdbDAO's on public_id
DECLARED_INDEXES: set[str] = {'name', 'public_id'}


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The template collection with the model's indexes built, purged and restored to its indexes afterwards"""
    collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
    collection.delete_many({'$or': [{'public_id': {'$in': SEEDED_IDS}}, {'name': {'$regex': f'^{NAME_PREFIX}'}}]})
    existing: set[str] = set(collection.index_information())
    created: list[str] = [name for name in collection.create_indexes(DocapiTemplate.get_index_keys())
                          if name not in existing]

    yield collection

    collection.delete_many({'$or': [{'public_id': {'$in': SEEDED_IDS}}, {'name': {'$regex': f'^{NAME_PREFIX}'}}]})
    # The session's other modules run against the collection without these indexes - leave it as found
    for name in created:
        collection.drop_index(name)


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> DocapiTemplatesManager:
    """A DocapiTemplatesManager on the test database"""
    return DocapiTemplatesManager(database_manager)


def _payload(public_id: Any, suffix: str) -> dict[str, Any]:
    """A template body as the routes hand it to the model"""
    return {'public_id': public_id, 'name': f'{NAME_PREFIX}{suffix}', 'template_data': '<p>{{ name }}</p>'}


class TestIndexes:
    """What the model declares builds as two unique indexes"""

    def test_both_unique_indexes_exist(self, collection) -> None:
        """Unique name and unique public_id"""
        indexes = {name: info for name, info in collection.index_information().items() if name != '_id_'}

        assert DECLARED_INDEXES <= set(indexes)
        assert all(indexes[name].get('unique') for name in DECLARED_INDEXES)


class TestStoreAndRead:
    """The manager round trip through the shared from_data / to_json"""

    def test_a_stored_template_reads_back_equal(self, collection, manager: DocapiTemplatesManager) -> None:
        """Insert, read, and the wire dict is what was stored"""
        manager.insert_template(DocapiTemplate(**_payload(TEMPLATE_ID, 'round-trip')))

        template = manager.get_template(TEMPLATE_ID)

        assert DocapiTemplate.to_json(template) == {key: value for key, value in collection.find_one(
            {'public_id': TEMPLATE_ID}, {'_id': 0}).items()}

    def test_a_document_without_active_reads_as_active(self, collection, manager: DocapiTemplatesManager) -> None:
        """Written directly, as an old document would be"""
        collection.insert_one(_payload(TEMPLATE_ID, 'no-active'))

        assert manager.get_template(TEMPLATE_ID).active is True

    def test_an_id_sent_as_text_is_stored_as_an_integer(self, collection, manager: DocapiTemplatesManager) -> None:
        """CmdbDAO converts it on construction"""
        manager.insert_template(_payload(str(TEXT_ID_TEMPLATE_ID), 'text-id'))

        assert isinstance(collection.find_one({'name': f'{NAME_PREFIX}text-id'})['public_id'], int)

    def test_a_second_insert_of_the_same_name_fails(self, collection, manager: DocapiTemplatesManager) -> None:
        """Re-run safe: the unique name index refuses the duplicate, one document stays"""
        manager.insert_template(_payload(TEMPLATE_ID, 'twice'))

        with pytest.raises(DocapiTemplatesManagerInsertError):
            manager.insert_template(_payload(TEXT_ID_TEMPLATE_ID, 'twice'))

        assert collection.count_documents({'name': f'{NAME_PREFIX}twice'}) == 1


def _validated(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """The body as the validate decorator hands it to the route"""
    validator = Validator(schema, purge_unknown=True)
    assert validator.validate(body), validator.errors

    return validator.document


def _schema_errors(document: dict[str, Any]) -> dict[str, Any]:
    """What DocapiTemplate.SCHEMA reports for a stored document"""
    validator = Validator(DocapiTemplate.SCHEMA)
    validator.validate({key: value for key, value in document.items() if key != '_id'})

    return validator.errors


class TestTheWriteSchema:
    """What the write schemas let through is a document the model's schema accepts"""

    def test_a_created_template_is_stored_valid(self, collection, manager: DocapiTemplatesManager) -> None:
        """The create path: validated body, stamped id and author, model, manager"""
        data = _validated(DOCAPI_TEMPLATE_CREATE_SCHEMA, {**_payload(None, 'schema-create'), 'header': {
            'activated': True, 'content': '<p/>', 'config': {'height': 40}}})
        data.update({'public_id': TEMPLATE_ID, 'author_id': 1})

        manager.insert_template(DocapiTemplate(**data))

        assert not _schema_errors(collection.find_one({'public_id': TEMPLATE_ID}))

    def test_an_old_document_reads_back_valid(self, collection, manager: DocapiTemplatesManager) -> None:
        """A document missing every optional key: the model's defaults are of their declared types"""
        collection.insert_one({'public_id': TEMPLATE_ID, 'name': f'{NAME_PREFIX}old'})

        assert not _schema_errors(DocapiTemplate.to_json(manager.get_template(TEMPLATE_ID)))

    def test_the_same_update_twice_stores_the_same_document(
        self, collection, manager: DocapiTemplatesManager,
    ) -> None:
        """Re-run safe: the update path, run twice"""
        manager.insert_template(_payload(TEMPLATE_ID, 'schema-update'))
        body = {**DocapiTemplate.to_json(manager.get_template(TEMPLATE_ID)), 'template_data': '<p>new</p>'}

        manager.update_template(DocapiTemplate(**_validated(DOCAPI_TEMPLATE_UPDATE_SCHEMA, body)))
        first = collection.find_one({'public_id': TEMPLATE_ID}, {'_id': 0})
        manager.update_template(DocapiTemplate(**_validated(DOCAPI_TEMPLATE_UPDATE_SCHEMA, body)))

        assert collection.find_one({'public_id': TEMPLATE_ID}, {'_id': 0}) == first
        assert not _schema_errors(first)
