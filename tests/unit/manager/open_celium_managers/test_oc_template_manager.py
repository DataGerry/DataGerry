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
Unit tests for cmdb.manager.open_celium_managers.oc_template_manager.OcTemplateManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each test stubs the connector verb with a fake response and asserts
the endpoint + payload, the parsed 2xx body (or None for an empty all-templates body), the
template-id guard, the connector-pair endpoint routing, and the OC error on a non-2xx response.
No HTTP, no Mongo.
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_template_manager import (
    OcTemplateManager,
    TEMPLATE_URL,
    ALL_TEMPLATES_URL,
)
from cmdb.errors.open_celium.template import OcTemplateGetError, OcTemplateCreateError
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

TEMPLATE_ID: str = 'tpl-1'
FROM_CONNECTOR_ID: int = 1
TO_CONNECTOR_ID: int = 2

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None, raw_text: str | None = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON/raw text body)."""
    if raw_text is not None:
        text = raw_text
    else:
        text = json.dumps(payload) if payload is not None else ''

    return SimpleNamespace(status_code=status_code, text=text)


@pytest.fixture(name='template_manager')
def fixture_template_manager() -> OcTemplateManager:
    """An OcTemplateManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcTemplateManager(MagicMock(), 'db_test')


# ---------------------------------------------------- create_template ----------------------------------------------- #

class TestCreateTemplate:
    """``create_template`` POSTs to /template."""

    def test_posts_and_returns_created(self, template_manager: OcTemplateManager) -> None:
        """A 2xx body is parsed and returned; the payload hits the template endpoint."""
        template_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'templateId': TEMPLATE_ID})

        result = template_manager.create_template({'name': 'tpl'})

        assert result == {'templateId': TEMPLATE_ID}
        template_manager.oc_connector.oc_post.assert_called_once_with({'name': 'tpl'}, TEMPLATE_URL)

    def test_non_2xx_raises_create_error(self, template_manager: OcTemplateManager) -> None:
        """A non-2xx response raises OcTemplateCreateError."""
        template_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcTemplateCreateError):
            template_manager.create_template({'name': 'tpl'})


# --------------------------------------------------- get_template_by_id --------------------------------------------- #

class TestGetTemplateById:
    """``get_template_by_id`` GETs /template/<id> and guards a missing id."""

    def test_missing_id_raises_without_http(self, template_manager: OcTemplateManager) -> None:
        """A falsy template id raises OcTemplateGetError before any HTTP call."""
        with pytest.raises(OcTemplateGetError):
            template_manager.get_template_by_id('')

        template_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_and_returns_body(self, template_manager: OcTemplateManager) -> None:
        """A 2xx body is parsed and returned from /template/<id>."""
        template_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'templateId': TEMPLATE_ID})

        result = template_manager.get_template_by_id(TEMPLATE_ID)

        assert result == {'templateId': TEMPLATE_ID}
        template_manager.oc_connector.oc_get.assert_called_once_with(f"{TEMPLATE_URL}/{TEMPLATE_ID}")

    def test_non_2xx_raises_get_error(self, template_manager: OcTemplateManager) -> None:
        """A non-2xx response raises OcTemplateGetError."""
        template_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcTemplateGetError):
            template_manager.get_template_by_id(TEMPLATE_ID)


# --------------------------------------------------- get_all_templates ---------------------------------------------- #

class TestGetAllTemplates:
    """``get_all_templates`` GETs the all-templates endpoint, optionally scoped to a connector pair."""

    def test_returns_all_templates(self, template_manager: OcTemplateManager) -> None:
        """With no connector ids the plain all-templates endpoint is queried."""
        template_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'templateId': TEMPLATE_ID}])

        result = template_manager.get_all_templates()

        assert result == [{'templateId': TEMPLATE_ID}]
        template_manager.oc_connector.oc_get.assert_called_once_with(ALL_TEMPLATES_URL)

    def test_scopes_to_connector_pair(self, template_manager: OcTemplateManager) -> None:
        """Both connector ids route to the from/to-scoped endpoint."""
        template_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [])

        template_manager.get_all_templates(FROM_CONNECTOR_ID, TO_CONNECTOR_ID)

        template_manager.oc_connector.oc_get.assert_called_once_with(
            f"{ALL_TEMPLATES_URL}/{FROM_CONNECTOR_ID}/{TO_CONNECTOR_ID}"
        )

    def test_single_connector_falls_back_to_plain_endpoint(self, template_manager: OcTemplateManager) -> None:
        """Only one connector id provided → the plain endpoint is used (both-or-none behavior)."""
        template_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [])

        template_manager.get_all_templates(from_connector=FROM_CONNECTOR_ID)

        template_manager.oc_connector.oc_get.assert_called_once_with(ALL_TEMPLATES_URL)

    def test_empty_body_returns_none(self, template_manager: OcTemplateManager) -> None:
        """A 2xx response with an empty body returns None."""
        template_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, raw_text='')

        assert template_manager.get_all_templates() is None

    def test_non_2xx_raises_get_error(self, template_manager: OcTemplateManager) -> None:
        """A non-2xx response raises OcTemplateGetError."""
        template_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcTemplateGetError):
            template_manager.get_all_templates()
