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
read helpers (``get_templates_by`` / ``get_template_by_name``) are tested directly.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate

from cmdb.errors.manager.docapi_templates_manager import DocapiTemplatesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_PUBLIC_ID: int = 42
NEW_TEMPLATE_ID: int = 7

TEMPLATE_DOC: dict[str, Any] = {'public_id': TEMPLATE_PUBLIC_ID, 'name': 'tpl'}
SECOND_TEMPLATE_DOC: dict[str, Any] = {'public_id': TEMPLATE_PUBLIC_ID + 1, 'name': 'tpl2'}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a DocapiTemplatesManager instance."""
    return MagicMock(spec=DocapiTemplatesManager)


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


# ----------------------------------------------------- get_templates_by --------------------------------------------- #

class TestGetTemplatesBy:
    """get_templates_by maps the get_many docs to DocapiTemplate instances."""

    def test_returns_models_for_each_match(self) -> None:
        """Every matched document is turned into a DocapiTemplate."""
        mgr = _mock_manager()
        mgr.get_many.return_value = [dict(TEMPLATE_DOC), dict(SECOND_TEMPLATE_DOC)]

        result = DocapiTemplatesManager.get_templates_by(mgr, active=True)

        assert all(isinstance(template, DocapiTemplate) for template in result)
        assert [template.name for template in result] == ['tpl', 'tpl2']
        mgr.get_many.assert_called_once_with(active=True)

    def test_wraps_failure_in_get_error(self) -> None:
        """A failure during retrieval surfaces as DocapiTemplatesManagerGetError."""
        mgr = _mock_manager()
        mgr.get_many.side_effect = RuntimeError('db down')

        with pytest.raises(DocapiTemplatesManagerGetError):
            DocapiTemplatesManager.get_templates_by(mgr, active=True)


# ---------------------------------------------------- get_template_by_name ------------------------------------------ #

class TestGetTemplateByName:
    """get_template_by_name returns the first match (or None) - no dead branches."""

    def test_returns_first_match(self) -> None:
        """A single matching document is returned as a DocapiTemplate (limit=1)."""
        mgr = _mock_manager()
        mgr.get_many.return_value = [dict(TEMPLATE_DOC)]

        result = DocapiTemplatesManager.get_template_by_name(mgr, name='tpl')

        assert isinstance(result, DocapiTemplate)
        assert result.name == 'tpl'
        mgr.get_many.assert_called_once_with(limit=1, name='tpl')

    def test_returns_none_when_no_match(self) -> None:
        """No match returns None."""
        mgr = _mock_manager()
        mgr.get_many.return_value = []

        assert DocapiTemplatesManager.get_template_by_name(mgr, name='nope') is None

    def test_wraps_failure_in_get_error(self) -> None:
        """A failure during retrieval surfaces as DocapiTemplatesManagerGetError."""
        mgr = _mock_manager()
        mgr.get_many.side_effect = RuntimeError('db down')

        with pytest.raises(DocapiTemplatesManagerGetError):
            DocapiTemplatesManager.get_template_by_name(mgr, name='tpl')


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
