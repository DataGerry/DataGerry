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
Integration tests for the DocapiTemplate CRUD surface of DocapiTemplatesManager

The unit suite asserts the delegation to GenericManager with a mocked manager; here the methods run
end-to-end through the bound ``docapi.templates`` collection:

- insert / get / update / delete round-trip (dict and model payloads)
- get_templates honours BuilderParameters and returns model-bound results plus the matching total
- get_templates_by / get_template_by_name resolve the requirements filter against the collection
- update_template is identified by the payload public_id and is a no-op for a missing id
- get_new_docapi_public_id draws a fresh incrementing counter value
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
# -------------------------------------------------------------------------------------------------------------------- #

TPL_ID_FOR_INSERT: int = 75101
TPL_ID_FOR_MODEL_INSERT: int = 75102
TPL_ID_FOR_GET: int = 75103
TPL_ID_FOR_UPDATE: int = 75104
TPL_ID_FOR_DELETE: int = 75105
TPL_ID_FOR_ITERATE_A: int = 75106
TPL_ID_FOR_ITERATE_B: int = 75107
TPL_ID_FOR_FILTER: int = 75108

MISSING_TPL_ID: int = 75900

FILTER_NAME: str = 'integration-filter-tpl'

ALL_TPL_IDS: list[int] = [
    TPL_ID_FOR_INSERT, TPL_ID_FOR_MODEL_INSERT, TPL_ID_FOR_GET, TPL_ID_FOR_UPDATE, TPL_ID_FOR_DELETE,
    TPL_ID_FOR_ITERATE_A, TPL_ID_FOR_ITERATE_B, TPL_ID_FOR_FILTER,
]


def _template_data(public_id: int, name: str = 'tpl') -> dict[str, Any]:
    """Builds a DocapiTemplate payload acceptable to ``insert_template`` / ``update_template``."""
    return {
        'public_id': public_id,
        'name': name,
        'label': 'Template',
        'active': True,
        'author_id': 1,
        'template_data': '<p>body</p>',
    }


def _delete_by_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes a set of DocapiTemplate docs directly via the collection."""
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _delete_by_ids(database_manager, database_name, ALL_TPL_IDS)


@pytest.fixture(name='docapi_templates_manager')
def fixture_docapi_templates_manager(database_manager: MongoDatabaseManager) -> DocapiTemplatesManager:
    """Provides a DocapiTemplatesManager wired to the test database."""
    return DocapiTemplatesManager(database_manager)


# ------------------------------------------------------- INSERT ----------------------------------------------------- #

class TestInsertTemplate:
    """``insert_template`` persists the doc and returns its public_id (dict and model payloads)."""

    def test_dict_payload_persists(
        self, docapi_templates_manager, database_manager, database_name,
    ) -> None:
        """A dict payload is wrapped in the model, persisted and its public_id returned."""
        try:
            returned_id = docapi_templates_manager.insert_template(_template_data(TPL_ID_FOR_INSERT))

            assert returned_id == TPL_ID_FOR_INSERT
            stored = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .find_one({'public_id': TPL_ID_FOR_INSERT})
            assert stored is not None
            assert stored['name'] == 'tpl'
        finally:
            _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_INSERT])

    def test_model_payload_persists(
        self, docapi_templates_manager, database_manager, database_name,
    ) -> None:
        """A DocapiTemplate instance is serialised and persisted."""
        try:
            template = DocapiTemplate(**_template_data(TPL_ID_FOR_MODEL_INSERT))
            returned_id = docapi_templates_manager.insert_template(template)

            assert returned_id == TPL_ID_FOR_MODEL_INSERT
            assert docapi_templates_manager.get_template(TPL_ID_FOR_MODEL_INSERT) is not None
        finally:
            _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_MODEL_INSERT])


# --------------------------------------------------------- GET ------------------------------------------------------ #

class TestGetTemplate:
    """``get_template`` returns a model instance or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed_one(self, docapi_templates_manager, database_manager, database_name):
        docapi_templates_manager.insert_template(_template_data(TPL_ID_FOR_GET))
        yield
        _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_GET])

    def test_returns_instance_for_existing_id(self, docapi_templates_manager: DocapiTemplatesManager) -> None:
        """An existing id returns a DocapiTemplate instance."""
        result = docapi_templates_manager.get_template(TPL_ID_FOR_GET)

        assert isinstance(result, DocapiTemplate)
        assert result.get_public_id() == TPL_ID_FOR_GET

    def test_returns_none_for_missing_id(self, docapi_templates_manager: DocapiTemplatesManager) -> None:
        """A missing id returns None rather than raising (GenericManager.get_item contract)."""
        assert docapi_templates_manager.get_template(MISSING_TPL_ID) is None


# ------------------------------------------------------- UPDATE ----------------------------------------------------- #

class TestUpdateTemplate:
    """``update_template`` writes the new payload, keyed by the payload public_id."""

    def test_persists_changes(
        self, docapi_templates_manager, database_manager, database_name,
    ) -> None:
        """The changed name is observable on a follow-up read."""
        try:
            docapi_templates_manager.insert_template(_template_data(TPL_ID_FOR_UPDATE))

            docapi_templates_manager.update_template(_template_data(TPL_ID_FOR_UPDATE, 'renamed'))

            stored = docapi_templates_manager.get_template(TPL_ID_FOR_UPDATE)
            assert stored is not None
            assert stored.name == 'renamed'
        finally:
            _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_UPDATE])

    def test_update_missing_id_is_a_noop(
        self, docapi_templates_manager, database_manager, database_name,
    ) -> None:
        """Updating an id that does not exist neither raises nor upserts a new doc."""
        docapi_templates_manager.update_template(_template_data(MISSING_TPL_ID))

        assert docapi_templates_manager.get_template(MISSING_TPL_ID) is None
        _delete_by_ids(database_manager, database_name, [MISSING_TPL_ID])


# ------------------------------------------------------- DELETE ----------------------------------------------------- #

class TestDeleteTemplate:
    """``delete_template`` removes the doc and reports whether a row was removed."""

    def test_removes_doc(self, docapi_templates_manager, database_manager, database_name) -> None:
        """Deleting an existing template makes it unretrievable and returns True."""
        docapi_templates_manager.insert_template(_template_data(TPL_ID_FOR_DELETE))

        assert docapi_templates_manager.delete_template(TPL_ID_FOR_DELETE) is True
        assert docapi_templates_manager.get_template(TPL_ID_FOR_DELETE) is None
        _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_DELETE])


# ------------------------------------------------------- ITERATE ---------------------------------------------------- #

class TestGetTemplates:
    """``get_templates`` returns model-bound results and the matching total."""

    def test_returns_inserted_rows_as_instances(
        self, docapi_templates_manager, database_manager, database_name,
    ) -> None:
        """Two inserted rows show up as ``DocapiTemplate`` instances in the IterationResult."""
        seeded = [TPL_ID_FOR_ITERATE_A, TPL_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                docapi_templates_manager.insert_template(_template_data(public_id))

            params = BuilderParameters(criteria={'public_id': {'$in': seeded}}, sort='public_id', order=1)
            iteration_result = docapi_templates_manager.get_templates(params)

            assert iteration_result.total == len(seeded)
            assert [tpl.get_public_id() for tpl in iteration_result.results] == seeded
            assert all(isinstance(tpl, DocapiTemplate) for tpl in iteration_result.results)
        finally:
            _delete_by_ids(database_manager, database_name, seeded)


# --------------------------------------------------- FILTERED READS ------------------------------------------------- #

class TestFilteredReads:
    """``get_templates_by`` / ``get_template_by_name`` resolve the requirements filter."""

    @pytest.fixture(autouse=True)
    def _seed_named(self, docapi_templates_manager, database_manager, database_name):
        docapi_templates_manager.insert_template(_template_data(TPL_ID_FOR_FILTER, FILTER_NAME))
        yield
        _delete_by_ids(database_manager, database_name, [TPL_ID_FOR_FILTER])

    def test_get_templates_by_returns_matches(self, docapi_templates_manager: DocapiTemplatesManager) -> None:
        """A name filter returns the matching template as a model instance."""
        results = docapi_templates_manager.get_templates_by(name=FILTER_NAME)

        assert [tpl.get_public_id() for tpl in results] == [TPL_ID_FOR_FILTER]
        assert all(isinstance(tpl, DocapiTemplate) for tpl in results)

    def test_get_minimal_templates_by_projects_only_public_id_and_label(
        self, docapi_templates_manager: DocapiTemplatesManager,
    ) -> None:
        """The minimal read returns only public_id + label dicts (server-side projection)."""
        results = docapi_templates_manager.get_minimal_templates_by(name=FILTER_NAME)

        assert results == [{'public_id': TPL_ID_FOR_FILTER, 'label': 'Template'}]

    def test_get_template_by_name_returns_single(self, docapi_templates_manager: DocapiTemplatesManager) -> None:
        """A name filter returns the first matching template."""
        result = docapi_templates_manager.get_template_by_name(name=FILTER_NAME)

        assert isinstance(result, DocapiTemplate)
        assert result.get_public_id() == TPL_ID_FOR_FILTER

    def test_get_template_by_name_returns_none_when_no_match(
        self, docapi_templates_manager: DocapiTemplatesManager,
    ) -> None:
        """A filter with no match returns None."""
        assert docapi_templates_manager.get_template_by_name(name='no-such-template') is None


# ------------------------------------------------ get_new_docapi_public_id ------------------------------------------ #

class TestGetNewPublicId:
    """``get_new_docapi_public_id`` draws an incrementing counter value."""

    def test_returns_incrementing_ids(self, docapi_templates_manager: DocapiTemplatesManager) -> None:
        """Two successive calls return distinct, increasing ids."""
        first_id = docapi_templates_manager.get_new_docapi_public_id()
        second_id = docapi_templates_manager.get_new_docapi_public_id()

        assert second_id > first_id
