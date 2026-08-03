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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_connector_helper

The three cache-first helpers (connector_in_subscription / validate_master_password /
get_accessible_connector_ids) prefer the local cache and fall back to the DG Service Portal; a
pre-resolved cached_user is reused instead of re-reading the cache.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from cmdb.interface.rest_api.routes.open_celium_routes.oc_connector_helper import (
    connector_in_subscription,
    validate_master_password,
    get_accessible_connector_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='gfSKkjoRzAxJwC', email='user@test.com')
CONNECTOR_ID: int = 7


class TestConnectorInSubscription:
    """connector_in_subscription resolves membership via the cache, else the Service Portal."""

    def test_uses_cache_when_cached_user_passed(self) -> None:
        """A pre-resolved cached user is validated via oc_id_exists; the cache is not re-read."""
        cached_manager = MagicMock()
        cached_manager.oc_id_exists.return_value = True
        dg_sp_manager = MagicMock()

        result = connector_in_subscription(
            REQUEST_USER, CONNECTOR_ID, cached_manager, dg_sp_manager, cached_user={'email': 'x'}
        )

        assert result is True
        cached_manager.get_cached_user.assert_not_called()
        dg_sp_manager.check_connector_in_sub.assert_not_called()

    def test_resolves_cache_when_not_passed(self) -> None:
        """With no cached_user passed, the cache is read once."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = {'email': 'x'}
        cached_manager.oc_id_exists.return_value = True

        result = connector_in_subscription(REQUEST_USER, CONNECTOR_ID, cached_manager, MagicMock())

        assert result is True
        cached_manager.get_cached_user.assert_called_once_with(REQUEST_USER.email)

    def test_falls_back_to_portal_when_not_cached(self) -> None:
        """An uncached user is validated via the Service Portal check."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = None  # no cached user -> portal fallback
        dg_sp_manager = MagicMock()
        dg_sp_manager.check_connector_in_sub.return_value = False

        result = connector_in_subscription(
            REQUEST_USER, CONNECTOR_ID, cached_manager, dg_sp_manager, cached_user=None
        )

        assert result is False
        dg_sp_manager.check_connector_in_sub.assert_called_once_with(
            CONNECTOR_ID, REQUEST_USER.email, REQUEST_USER.database
        )


class TestValidateMasterPassword:
    """validate_master_password checks the cache first, else the Service Portal."""

    def test_cache_path(self) -> None:
        """A cached user validates the master password against the cached value."""
        cached_manager = MagicMock()
        cached_manager.check_cached_master_password.return_value = True

        result = validate_master_password(
            REQUEST_USER, 'pw', cached_manager, MagicMock(), cached_user={'email': 'x'}
        )

        assert result is True
        cached_manager.check_cached_master_password.assert_called_once()

    def test_portal_fallback(self) -> None:
        """An uncached user validates the master password via the Service Portal."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = None
        dg_sp_manager = MagicMock()
        dg_sp_manager.check_master_pw.return_value = False

        result = validate_master_password(REQUEST_USER, 'pw', cached_manager, dg_sp_manager)

        assert result is False
        dg_sp_manager.check_master_pw.assert_called_once_with('pw', REQUEST_USER.email, REQUEST_USER.database)


class TestGetAccessibleConnectorIds:
    """get_accessible_connector_ids resolves ids via the cache, else the Service Portal."""

    def test_cache_path(self) -> None:
        """A cached user's connector ids come from the cache."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = {'email': 'x'}
        cached_manager.get_oc_ids.return_value = [1, 2]

        result = get_accessible_connector_ids(REQUEST_USER, cached_manager, MagicMock())

        assert result == [1, 2]

    def test_cache_path_none_becomes_empty(self) -> None:
        """A cached user with no ids yields an empty list (not None)."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = {'email': 'x'}
        cached_manager.get_oc_ids.return_value = None

        assert get_accessible_connector_ids(REQUEST_USER, cached_manager, MagicMock()) == []

    def test_portal_fallback(self) -> None:
        """An uncached user's connector ids come from the Service Portal."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = None
        dg_sp_manager = MagicMock()
        dg_sp_manager.get_connector_ids.return_value = [9]

        result = get_accessible_connector_ids(REQUEST_USER, cached_manager, dg_sp_manager)

        assert result == [9]
        dg_sp_manager.get_connector_ids.assert_called_once_with(REQUEST_USER.email, REQUEST_USER.database)
