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
Unit tests for cmdb.manager.open_celium_managers.oc_connector_manager.OcConnectorManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each test stubs the connector verb with a fake response and asserts
the endpoint + payload, the parsed 2xx body, and the per-operation OC error on a non-2xx response
(or the bool/None contract for the boolean / all-connectors methods). The manager runs on-premise
(the autouse app context defaults cloud_mode/local_mode to False), so no OC master password env is
required. No HTTP, no Mongo.
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_connector_manager import (
    OcConnectorManager,
    CONNECTOR_URL,
    CHECK_CONNECTOR_URL,
    CONNECTORS_BY_IDS_URL,
    ALL_CONNECTORS_URL,
    CHECK_MASTER_PW_URL,
    CHECK_MASTER_PW_EXISTS_URL,
    CONNECTOR_EXISTS_URL,
)
from cmdb.errors.open_celium.connector import (
    OcConnectorCreateError,
    OcConnectorGetError,
    OcConnectorUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

CONNECTOR_ID: int = 7
CONNECTOR_TITLE: str = 'my-connector'
MASTER_PW: str = 'secret-pw'

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None, raw_text: str | None = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON/raw text body)."""
    if raw_text is not None:
        text = raw_text
    else:
        text = json.dumps(payload) if payload is not None else ''

    return SimpleNamespace(status_code=status_code, text=text)


@pytest.fixture(name='connector_manager')
def fixture_connector_manager() -> OcConnectorManager:
    """An OcConnectorManager whose OcApiConnector is a MagicMock (no HTTP); on-premise via app context."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcConnectorManager(MagicMock(), 'db_test')


# --------------------------------------------------- create_connector ----------------------------------------------- #

class TestCreateConnector:
    """``create_connector`` POSTs to /connector."""

    def test_posts_and_returns_created(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx body is parsed and returned; the payload hits the connector endpoint."""
        connector_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'connectorId': CONNECTOR_ID})

        result = connector_manager.create_connector({'title': CONNECTOR_TITLE})

        assert result == {'connectorId': CONNECTOR_ID}
        connector_manager.oc_connector.oc_post.assert_called_once_with({'title': CONNECTOR_TITLE}, CONNECTOR_URL)

    def test_non_2xx_raises_create_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorCreateError."""
        connector_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorCreateError):
            connector_manager.create_connector({'title': CONNECTOR_TITLE})


# ---------------------------------------------------- check_connector ----------------------------------------------- #

class TestCheckConnector:
    """``check_connector`` returns a bool from the credentials-check endpoint."""

    def test_2xx_returns_true(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx response means the credentials are valid → True."""
        connector_manager.oc_connector.oc_post.return_value = _response(OK_STATUS)

        assert connector_manager.check_connector({'invoker': 'x'}) is True
        connector_manager.oc_connector.oc_post.assert_called_once_with({'invoker': 'x'}, CHECK_CONNECTOR_URL)

    def test_non_2xx_returns_false(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response means invalid → False (no raise)."""
        connector_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        assert connector_manager.check_connector({'invoker': 'x'}) is False


# ---------------------------------------------------- check_master_pw ----------------------------------------------- #

class TestCheckMasterPw:
    """``check_master_pw`` returns a bool by default, or the raw body when raw=True."""

    def test_valid_returns_true(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx response returns True (non-raw) and queries the master-password endpoint with the pw."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'ok': True})

        assert connector_manager.check_master_pw(MASTER_PW) is True
        connector_manager.oc_connector.oc_get.assert_called_once_with(CHECK_MASTER_PW_URL, MASTER_PW)

    def test_invalid_returns_false(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response returns False (non-raw)."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        assert connector_manager.check_master_pw(MASTER_PW) is False

    def test_raw_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """With raw=True a 2xx response returns the parsed body."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'status': 'set'})

        assert connector_manager.check_master_pw(MASTER_PW, raw=True) == {'status': 'set'}

    def test_raw_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """With raw=True a non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.check_master_pw(MASTER_PW, raw=True)


# ------------------------------------------------- check_master_pw_exists ------------------------------------------- #

class TestCheckMasterPwExists:
    """``check_master_pw_exists`` returns the existence body."""

    def test_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx response body is parsed and returned from the exists endpoint."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'exists': True})

        assert connector_manager.check_master_pw_exists() == {'exists': True}
        connector_manager.oc_connector.oc_get.assert_called_once_with(CHECK_MASTER_PW_EXISTS_URL)

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.check_master_pw_exists()


# ------------------------------------------------- get_connectors_by_ids -------------------------------------------- #

class TestGetConnectorsByIds:
    """``get_connectors_by_ids`` POSTs the id list and guards an empty list."""

    def test_empty_ids_raises_without_http(self, connector_manager: OcConnectorManager) -> None:
        """An empty id list raises OcConnectorGetError before any HTTP call."""
        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connectors_by_ids([])

        connector_manager.oc_connector.oc_post.assert_not_called()

    def test_posts_identifiers_and_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """The ids are sent under 'identifiers' to the by-ids endpoint and the body is returned."""
        connector_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, [{'connectorId': CONNECTOR_ID}])

        result = connector_manager.get_connectors_by_ids([CONNECTOR_ID])

        assert result == [{'connectorId': CONNECTOR_ID}]
        connector_manager.oc_connector.oc_post.assert_called_once_with(
            {'identifiers': [CONNECTOR_ID]}, CONNECTORS_BY_IDS_URL
        )

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connectors_by_ids([CONNECTOR_ID])


# ----------------------------------------------------- get_connector ------------------------------------------------ #

class TestGetConnector:
    """``get_connector`` GETs /connector/<id> (with an optional master password) and guards a falsy id."""

    def test_falsy_id_raises_without_http(self, connector_manager: OcConnectorManager) -> None:
        """A falsy connector id raises OcConnectorGetError before any HTTP call."""
        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connector(0)

        connector_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_with_password_and_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """The connector is fetched by id with the provided password."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'connectorId': CONNECTOR_ID})

        result = connector_manager.get_connector(CONNECTOR_ID, MASTER_PW)

        assert result == {'connectorId': CONNECTOR_ID}
        connector_manager.oc_connector.oc_get.assert_called_once_with(f"{CONNECTOR_URL}/{CONNECTOR_ID}", MASTER_PW)

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connector(CONNECTOR_ID)


# -------------------------------------------------- get_connector_by_name ------------------------------------------- #

class TestGetConnectorByName:
    """``get_connector_by_name`` GETs /connector?title=<title> and guards a missing title."""

    def test_missing_title_raises_without_http(self, connector_manager: OcConnectorManager) -> None:
        """A falsy title raises OcConnectorGetError before any HTTP call."""
        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connector_by_name('')

        connector_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_by_title_and_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """The connector is fetched by title query and the body returned."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'title': CONNECTOR_TITLE})

        result = connector_manager.get_connector_by_name(CONNECTOR_TITLE)

        assert result == {'title': CONNECTOR_TITLE}
        connector_manager.oc_connector.oc_get.assert_called_once_with(f"{CONNECTOR_URL}?title={CONNECTOR_TITLE}", None)

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.get_connector_by_name(CONNECTOR_TITLE)


# ---------------------------------------------------- connector_exists ---------------------------------------------- #

class TestConnectorExists:
    """``connector_exists`` returns the 'result' flag from the exists endpoint."""

    def test_missing_title_raises_without_http(self, connector_manager: OcConnectorManager) -> None:
        """A falsy title raises OcConnectorGetError before any HTTP call."""
        with pytest.raises(OcConnectorGetError):
            connector_manager.connector_exists('')

        connector_manager.oc_connector.oc_get.assert_not_called()

    def test_returns_result_flag(self, connector_manager: OcConnectorManager) -> None:
        """The 'result' value from the body is returned."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'result': True})

        assert connector_manager.connector_exists(CONNECTOR_TITLE) is True
        connector_manager.oc_connector.oc_get.assert_called_once_with(f"{CONNECTOR_EXISTS_URL}/{CONNECTOR_TITLE}")

    def test_missing_result_key_returns_false(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx body without a 'result' key returns False (the method's -> bool contract)."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {})

        assert connector_manager.connector_exists(CONNECTOR_TITLE) is False

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.connector_exists(CONNECTOR_TITLE)


# ---------------------------------------------------- get_all_connectors -------------------------------------------- #

class TestGetAllConnectors:
    """``get_all_connectors`` returns the list, or None for an empty 2xx body."""

    def test_returns_connectors(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx response with a body returns the parsed connector list."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'connectorId': CONNECTOR_ID}])

        result = connector_manager.get_all_connectors()

        assert result == [{'connectorId': CONNECTOR_ID}]
        connector_manager.oc_connector.oc_get.assert_called_once_with(ALL_CONNECTORS_URL)

    def test_empty_body_returns_none(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx response with an empty body returns None."""
        connector_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, raw_text='')

        assert connector_manager.get_all_connectors() is None

    def test_non_2xx_raises_get_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorGetError."""
        connector_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorGetError):
            connector_manager.get_all_connectors()


# ---------------------------------------------------- update_connector ---------------------------------------------- #

class TestUpdateConnector:
    """``update_connector`` PUTs to /connector/<id>."""

    def test_puts_and_returns_body(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx body is parsed and returned from the PUT."""
        connector_manager.oc_connector.oc_put.return_value = _response(OK_STATUS, {'connectorId': CONNECTOR_ID})

        result = connector_manager.update_connector({'title': 'renamed'}, CONNECTOR_ID)

        assert result == {'connectorId': CONNECTOR_ID}
        connector_manager.oc_connector.oc_put.assert_called_once_with(
            {'title': 'renamed'}, f"{CONNECTOR_URL}/{CONNECTOR_ID}"
        )

    def test_non_2xx_raises_update_error(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx response raises OcConnectorUpdateError."""
        connector_manager.oc_connector.oc_put.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectorUpdateError):
            connector_manager.update_connector({'title': 'renamed'}, CONNECTOR_ID)


# ---------------------------------------------------- delete_connector ---------------------------------------------- #

class TestDeleteConnector:
    """``delete_connector`` returns a bool (never raises)."""

    def test_2xx_returns_true(self, connector_manager: OcConnectorManager) -> None:
        """A 2xx delete returns True."""
        connector_manager.oc_connector.oc_delete.return_value = _response(OK_STATUS)

        assert connector_manager.delete_connector(CONNECTOR_ID) is True
        connector_manager.oc_connector.oc_delete.assert_called_once_with(f"{CONNECTOR_URL}/{CONNECTOR_ID}")

    def test_non_2xx_returns_false(self, connector_manager: OcConnectorManager) -> None:
        """A non-2xx delete returns False rather than raising."""
        connector_manager.oc_connector.oc_delete.return_value = _response(ERROR_STATUS)

        assert connector_manager.delete_connector(CONNECTOR_ID) is False


# ------------------------------------------------------ get_master_pw ----------------------------------------------- #

class TestGetMasterPw:
    """``get_master_pw`` returns the cached master password (None on-premise)."""

    def test_returns_none_on_premise(self, connector_manager: OcConnectorManager) -> None:
        """On-premise (no OC master password env) the cached value is None."""
        assert connector_manager.get_master_pw() is None
