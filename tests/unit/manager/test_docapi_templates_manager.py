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
Unit tests for cmdb.manager.docapi_templates_manager.DocapiTemplatesManager

Pure tests: no Mongo. DocapiTemplatesManager is a GenericManager subclass, so the CRUD methods are
thin forwarders to the generic item-level CRUD (insert_item / get_item / iterate_items /
update_item / delete_item) - those primitives + their error wrapping are covered by the
GenericManager suite. Here each method is invoked unbound against a
``MagicMock(spec=DocapiTemplatesManager)`` and asserted to delegate correctly; the docapi-specific
reads (``get_minimal_templates`` / ``get_template_by_name``) are tested directly.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.docapi_templates_manager import MINIMAL_TEMPLATE_PROJECTION, DocapiTemplatesManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_PUBLIC_ID: int = 42
NEW_TEMPLATE_ID: int = 7

TEMPLATE_DOC: dict[str, Any] = {'public_id': TEMPLATE_PUBLIC_ID, 'name': 'tpl'}
# A stored template without its required name - what DocapiTemplate.from_data refuses
UNREADABLE_TEMPLATE_DOC: dict[str, Any] = {'public_id': TEMPLATE_PUBLIC_ID}
DB_FAILURE: str = 'db down'

# What the minimal read is handed and answers - distinct values, so a swapped argument fails
PAGED_QUERY: list[dict[str, Any]] = [{'$match': {'active': True}}, {'$skip': 10}, {'$limit': 5}]
COUNT_QUERY: list[dict[str, Any]] = [{'$match': {'active': True}}, {'$count': 'total'}]
CRITERIA: list[dict[str, Any]] = [{'$match': {'active': True}}]
TIME_LIMIT_MS: int = 1234
MINIMAL_ROWS: list[dict[str, Any]] = [{'public_id': TEMPLATE_PUBLIC_ID, 'label': 'Template'}]
MINIMAL_TOTAL: int = 17


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a DocapiTemplatesManager instance, with the model's declared errors bound"""
    mgr = MagicMock(spec=DocapiTemplatesManager)
    mgr._model_errors.return_value = (DocapiTemplate.INIT_FROM_DATA_ERROR, DocapiTemplate.TO_JSON_ERROR)

    return mgr


# ----------------------------------------------------- insert_template ---------------------------------------------- #

class TestInsertTemplate:
    """insert_template normalises to a model instance and forwards to insert_item."""

    def test_dict_is_wrapped_in_model_then_inserted(self) -> None:
        """A dict payload is turned into a DocapiTemplate before insert_item."""
        mgr = _mock_manager()
        mgr.insert_item.return_value = NEW_TEMPLATE_ID

        result = DocapiTemplatesManager.insert_template(mgr, dict(TEMPLATE_DOC))

        assert result == NEW_TEMPLATE_ID
        inserted = mgr.insert_item.call_args.args[0]
        assert isinstance(inserted, DocapiTemplate)
        assert inserted.name == 'tpl'

    def test_model_instance_is_forwarded_unchanged(self) -> None:
        """A DocapiTemplate instance is forwarded to insert_item as-is."""
        mgr = _mock_manager()
        template = DocapiTemplate(**TEMPLATE_DOC)

        DocapiTemplatesManager.insert_template(mgr, template)

        mgr.insert_item.assert_called_once_with(template)


# ------------------------------------------------------ get_template ------------------------------------------------ #

class TestGetTemplate:
    """get_template forwards to the generic get_item (model instance)."""

    def test_delegates_to_get_item(self) -> None:
        """get_template fetches the model instance via get_item(as_dict=False)."""
        mgr = _mock_manager()
        sentinel = MagicMock(name='template')
        mgr.get_item.return_value = sentinel

        assert DocapiTemplatesManager.get_template(mgr, TEMPLATE_PUBLIC_ID) is sentinel
        mgr.get_item.assert_called_once_with(TEMPLATE_PUBLIC_ID, as_dict=False)


# ------------------------------------------------------ get_templates ----------------------------------------------- #

class TestGetTemplates:
    """get_templates forwards to the generic iterate_items."""

    def test_delegates_to_iterate_items(self) -> None:
        """get_templates forwards the builder params to iterate_items."""
        mgr = _mock_manager()
        sentinel = MagicMock(name='iteration_result')
        mgr.iterate_items.return_value = sentinel
        builder_params = MagicMock(name='builder_params')

        assert DocapiTemplatesManager.get_templates(mgr, builder_params) is sentinel
        mgr.iterate_items.assert_called_once_with(builder_params)


# --------------------------------------------------- get_minimal_templates ------------------------------------------ #

def _minimal_manager(count_result: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
    """A manager whose query builder answers PAGED_QUERY / COUNT_QUERY, and builder params carrying CRITERIA"""
    mgr = _mock_manager()
    mgr.query_builder = MagicMock()
    mgr.query_builder.build.return_value = list(PAGED_QUERY)
    mgr.query_builder.count.return_value = list(COUNT_QUERY)
    mgr.aggregate_within_time_limit.side_effect = [list(MINIMAL_ROWS), count_result]

    builder_params = MagicMock(time_limit_ms=TIME_LIMIT_MS)
    builder_params.get_criteria.return_value = CRITERIA

    return mgr, builder_params


class TestGetMinimalTemplates:
    """get_minimal_templates runs the paged query with the projection appended LAST, plus the count"""

    def test_answers_the_projected_page_and_the_total(self) -> None:
        """The rows as the database answered them, and the count pipeline's total"""
        mgr, builder_params = _minimal_manager([{'total': MINIMAL_TOTAL}])

        assert DocapiTemplatesManager.get_minimal_templates(mgr, builder_params) == (MINIMAL_ROWS, MINIMAL_TOTAL)

    def test_the_projection_follows_the_paging(self) -> None:
        """Appended after skip / limit, so a sort on a dropped key still orders the page"""
        mgr, builder_params = _minimal_manager([{'total': MINIMAL_TOTAL}])

        DocapiTemplatesManager.get_minimal_templates(mgr, builder_params)

        page_call, count_call = mgr.aggregate_within_time_limit.call_args_list
        assert page_call.args == ([*PAGED_QUERY, {'$project': MINIMAL_TEMPLATE_PROJECTION}], TIME_LIMIT_MS)
        assert count_call.args == (COUNT_QUERY, TIME_LIMIT_MS)
        mgr.query_builder.build.assert_called_once_with(builder_params)
        mgr.query_builder.count.assert_called_once_with(CRITERIA)

    def test_no_match_counts_zero(self) -> None:
        """The count pipeline answers nothing when nothing matches"""
        mgr, builder_params = _minimal_manager([])

        assert DocapiTemplatesManager.get_minimal_templates(mgr, builder_params)[1] == 0

    def test_a_failed_read_becomes_the_iteration_error(self) -> None:
        """The route maps DocapiTemplatesManagerIterationError to a 400; the read's own error is carried"""
        mgr, builder_params = _minimal_manager([])
        failure = BaseManagerIterationError(DB_FAILURE)
        mgr.aggregate_within_time_limit.side_effect = failure

        with pytest.raises(DocapiTemplatesManagerIterationError) as caught:
            DocapiTemplatesManager.get_minimal_templates(mgr, builder_params)

        assert caught.value.args[0] is failure

    def test_a_programming_error_propagates(self) -> None:
        """A bug in the read reaches the route's 500 as itself"""
        mgr, builder_params = _minimal_manager([])
        mgr.aggregate_within_time_limit.side_effect = RuntimeError(DB_FAILURE)

        with pytest.raises(RuntimeError):
            DocapiTemplatesManager.get_minimal_templates(mgr, builder_params)


# ---------------------------------------------------- get_template_by_name ------------------------------------------ #

class TestGetTemplateByName:
    """get_template_by_name returns the first match (or None) - no dead branches."""

    def test_returns_first_match(self) -> None:
        """A single matching document is returned as a DocapiTemplate (limit=1)."""
        mgr = _mock_manager()
        mgr.get_many.return_value = [dict(TEMPLATE_DOC)]

        result = DocapiTemplatesManager.get_template_by_name(mgr, 'tpl')

        assert isinstance(result, DocapiTemplate)
        assert result.name == 'tpl'
        mgr.get_many.assert_called_once_with(limit=1, criteria={'name': 'tpl'})

    def test_returns_none_when_no_match(self) -> None:
        """No match returns None."""
        mgr = _mock_manager()
        mgr.get_many.return_value = []

        assert DocapiTemplatesManager.get_template_by_name(mgr, 'nope') is None

    def test_wraps_a_read_failure_in_get_error(self) -> None:
        """The read's BaseManagerGetError surfaces as DocapiTemplatesManagerGetError, carrying it"""
        mgr = _mock_manager()
        failure = BaseManagerGetError(DB_FAILURE)
        mgr.get_many.side_effect = failure

        with pytest.raises(DocapiTemplatesManagerGetError) as caught:
            DocapiTemplatesManager.get_template_by_name(mgr, 'tpl')

        assert caught.value.args[0] is failure

    def test_wraps_an_unreadable_template_in_get_error(self) -> None:
        """A stored template the model refuses is the read's GetError"""
        mgr = _mock_manager()
        mgr.get_many.return_value = [dict(UNREADABLE_TEMPLATE_DOC)]

        with pytest.raises(DocapiTemplatesManagerGetError) as caught:
            DocapiTemplatesManager.get_template_by_name(mgr, 'tpl')

        assert isinstance(caught.value.args[0], DocapiTemplate.INIT_FROM_DATA_ERROR)

    def test_a_programming_error_propagates(self) -> None:
        """A bug in the read is not reported as a failed read"""
        mgr = _mock_manager()
        mgr.get_many.side_effect = RuntimeError(DB_FAILURE)

        with pytest.raises(RuntimeError):
            DocapiTemplatesManager.get_template_by_name(mgr, 'tpl')


# ----------------------------------------------------- update_template ---------------------------------------------- #

class TestUpdateTemplate:
    """update_template forwards to update_item keyed by the template's own public_id."""

    def test_dict_is_wrapped_and_updated_by_public_id(self) -> None:
        """A dict payload is wrapped in a model and updated keyed by its public_id."""
        mgr = _mock_manager()

        DocapiTemplatesManager.update_template(mgr, dict(TEMPLATE_DOC))

        called_id, called_data = mgr.update_item.call_args.args
        assert called_id == TEMPLATE_PUBLIC_ID
        assert isinstance(called_data, DocapiTemplate)

    def test_model_instance_is_updated_by_public_id(self) -> None:
        """A DocapiTemplate instance is updated keyed by its public_id."""
        mgr = _mock_manager()
        template = DocapiTemplate(**TEMPLATE_DOC)

        DocapiTemplatesManager.update_template(mgr, template)

        mgr.update_item.assert_called_once_with(TEMPLATE_PUBLIC_ID, template)


# ----------------------------------------------------- delete_template ---------------------------------------------- #

class TestDeleteTemplate:
    """delete_template forwards to the generic delete_item."""

    def test_delegates_to_delete_item(self) -> None:
        """delete_template forwards the public_id to delete_item and returns its result."""
        mgr = _mock_manager()
        mgr.delete_item.return_value = True

        assert DocapiTemplatesManager.delete_template(mgr, TEMPLATE_PUBLIC_ID) is True
        mgr.delete_item.assert_called_once_with(TEMPLATE_PUBLIC_ID)


class TestGetNewDocapiPublicId:
    """The id reservation of the create route answers the manager's own GetError on a failed counter."""

    def test_answers_the_reserved_id(self) -> None:
        """The counter is read with inc_id=True and its value answered"""
        mgr = _mock_manager()
        mgr.get_next_public_id.return_value = NEW_TEMPLATE_ID

        assert DocapiTemplatesManager.get_new_docapi_public_id(mgr) == NEW_TEMPLATE_ID
        mgr.get_next_public_id.assert_called_once_with(inc_id=True)

    def test_a_counter_failure_becomes_a_get_error(self) -> None:
        """The counter's BaseManagerGetError surfaces as DocapiTemplatesManagerGetError, carrying it"""
        mgr = _mock_manager()
        failure = BaseManagerGetError(DB_FAILURE)
        mgr.get_next_public_id.side_effect = failure

        with pytest.raises(DocapiTemplatesManagerGetError) as caught:
            DocapiTemplatesManager.get_new_docapi_public_id(mgr)

        assert caught.value.args[0] is failure

    def test_a_programming_error_propagates(self) -> None:
        """A bug in the reservation propagates as itself"""
        mgr = _mock_manager()
        mgr.get_next_public_id.side_effect = RuntimeError(DB_FAILURE)

        with pytest.raises(RuntimeError):
            DocapiTemplatesManager.get_new_docapi_public_id(mgr)
