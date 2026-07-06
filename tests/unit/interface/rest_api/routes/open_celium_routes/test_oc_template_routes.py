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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_template_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with OcTemplateManager patched at the route module path - no external
OpenCelium HTTP, no Mongo. The app runs on-premise (cloud_mode/local_mode False), so the detailed
route filters on the "DataGerry" invoker name (the cloud "DataGerryCloud" branch is skipped). The
AUTOMATIONS 403 gate is covered by the functional automations-gating suite.

These pin the handler glue: the manager call, the success payload, the DataGerry-template filter and
the per-error abort mapping.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_template_routes import (
    create_oc_template,
    get_oc_template,
    get_all_oc_templates,
    get_all_oc_templates_detailed,
)
from cmdb.errors.open_celium.template import OcTemplateCreateError, OcTemplateGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_template_routes'

TEMPLATE_ID: str = 'tpl-1'
FROM_CONNECTOR_ID: int = 1
TO_CONNECTOR_ID: int = 2
DATAGERRY_INVOKER: str = 'DataGerry'

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='db_test', email='user@test.com', public_id=1)


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (handle_oc_errors / insert_request_user / verify_api_access)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


def _template_with_invoker(invoker_name: str) -> dict[str, Any]:
    """Builds a template whose fromConnector invoker carries the given name."""
    return {
        'connection': {
            'fromConnector': {'invoker': {'name': invoker_name}},
            'toConnector': {'invoker': {'name': 'Other'}},
        }
    }


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> BaseCmdbApp:
    """An on-premise BaseCmdbApp (cloud_mode/local_mode False) with a stub database_manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = False
    app.local_mode = False

    return app


@pytest.fixture(name='template_manager')
def fixture_template_manager() -> MagicMock:
    """The OcTemplateManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_manager')
def fixture_patched_manager(template_manager: MagicMock) -> Any:
    """Patches OcTemplateManager at the route module path."""
    with patch(f'{ROUTE_PATH}.OcTemplateManager', return_value=template_manager):
        yield


# --------------------------------------------------- create_oc_template --------------------------------------------- #

class TestCreateOcTemplate:
    """``create_oc_template`` forwards the payload to the manager."""

    def test_creates_and_returns_template(self, flask_app, template_manager, patched_manager) -> None:
        """The created template is returned with 200."""
        del patched_manager
        template_manager.create_template.return_value = {'templateId': TEMPLATE_ID}

        with flask_app.test_request_context(json={'name': 'tpl'}):
            response = _unwrap(create_oc_template)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        template_manager.create_template.assert_called_once_with({'name': 'tpl'})

    def test_create_error_returns_500(self, flask_app, template_manager, patched_manager) -> None:
        """An OcTemplateCreateError maps to 500."""
        del patched_manager
        template_manager.create_template.side_effect = OcTemplateCreateError('boom')

        with flask_app.test_request_context(json={'name': 'tpl'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_template)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------------- get_oc_template ---------------------------------------------- #

class TestGetOcTemplate:
    """``get_oc_template`` returns a single template by id."""

    def test_returns_template(self, flask_app, template_manager, patched_manager) -> None:
        """The manager's template is returned with 200."""
        del patched_manager
        template_manager.get_template_by_id.return_value = {'templateId': TEMPLATE_ID}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_template)(request_user=REQUEST_USER, template_id=TEMPLATE_ID)

        assert response.status_code == HTTPStatus.OK
        template_manager.get_template_by_id.assert_called_once_with(TEMPLATE_ID)

    def test_get_error_returns_500(self, flask_app, template_manager, patched_manager) -> None:
        """An OcTemplateGetError maps to 500."""
        del patched_manager
        template_manager.get_template_by_id.side_effect = OcTemplateGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_template)(request_user=REQUEST_USER, template_id=TEMPLATE_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- get_all_oc_templates ------------------------------------------- #

class TestGetAllOcTemplates:
    """``get_all_oc_templates`` returns all templates."""

    def test_returns_all_templates(self, flask_app, template_manager, patched_manager) -> None:
        """All templates are returned with 200."""
        del patched_manager
        template_manager.get_all_templates.return_value = [{'templateId': TEMPLATE_ID}]

        with flask_app.test_request_context():
            response = _unwrap(get_all_oc_templates)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        template_manager.get_all_templates.assert_called_once_with()

    def test_get_error_returns_500(self, flask_app, template_manager, patched_manager) -> None:
        """An OcTemplateGetError maps to 500."""
        del patched_manager
        template_manager.get_all_templates.side_effect = OcTemplateGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_templates)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------- get_all_oc_templates_detailed -------------------------------------- #

class TestGetAllOcTemplatesDetailed:
    """``get_all_oc_templates_detailed`` keeps only templates whose invoker is the DataGerry one."""

    def test_filters_to_datagerry_templates(self, flask_app, template_manager, patched_manager) -> None:
        """Only templates carrying the 'DataGerry' invoker survive the filter (on-premise)."""
        del patched_manager
        matching = _template_with_invoker(DATAGERRY_INVOKER)
        template_manager.get_all_templates.return_value = [matching, _template_with_invoker('Foreign')]

        with flask_app.test_request_context():
            response = _unwrap(get_all_oc_templates_detailed)(
                request_user=REQUEST_USER,
                from_connector_id=FROM_CONNECTOR_ID,
                to_connector_id=TO_CONNECTOR_ID,
            )

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == [matching]
        template_manager.get_all_templates.assert_called_once_with(FROM_CONNECTOR_ID, TO_CONNECTOR_ID)

    def test_no_templates_returns_empty(self, flask_app, template_manager, patched_manager) -> None:
        """When the manager returns nothing the response is an empty list."""
        del patched_manager
        template_manager.get_all_templates.return_value = None

        with flask_app.test_request_context():
            response = _unwrap(get_all_oc_templates_detailed)(
                request_user=REQUEST_USER,
                from_connector_id=FROM_CONNECTOR_ID,
                to_connector_id=TO_CONNECTOR_ID,
            )

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_get_error_returns_500(self, flask_app, template_manager, patched_manager) -> None:
        """An OcTemplateGetError maps to 500."""
        del patched_manager
        template_manager.get_all_templates.side_effect = OcTemplateGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_templates_detailed)(
                    request_user=REQUEST_USER,
                    from_connector_id=FROM_CONNECTOR_ID,
                    to_connector_id=TO_CONNECTOR_ID,
                )

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
