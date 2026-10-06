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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_helper

connection_in_subscription prefers the local user cache and falls back to the DG Service Portal only
on a cache miss.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from cmdb.open_celium import CachedOcIdType
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_helper import connection_in_subscription
# -------------------------------------------------------------------------------------------------------------------- #

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='gfSKkjoRzAxJwC', email='user@test.com')
CONNECTION_ID: int = 5


class TestConnectionInSubscription:
    """connection_in_subscription resolves membership via the cache, else the Service Portal."""

    def test_uses_cache_when_user_is_cached(self) -> None:
        """A cached user is validated via oc_id_exists; the Service Portal is not contacted."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = {'email': REQUEST_USER.email}
        cached_manager.oc_id_exists.return_value = True
        dg_sp_manager = MagicMock()

        result = connection_in_subscription(REQUEST_USER, CONNECTION_ID, cached_manager, dg_sp_manager)

        assert result is True
        cached_manager.oc_id_exists.assert_called_once()
        dg_sp_manager.check_connection_in_sub.assert_not_called()

    def test_a_miss_is_seeded_from_the_portal_and_checked_in_the_cache(self) -> None:
        """An uncached user is seeded once from the portal; the id is then looked up in the stored entry."""
        cached_manager = MagicMock()
        seeded = {'email': REQUEST_USER.email}
        cached_manager.get_cached_user.side_effect = [None, seeded]
        cached_manager.oc_id_exists.return_value = True
        dg_sp_manager = MagicMock()
        dg_sp_manager.get_dg_sp_user_data.return_value = {'email': REQUEST_USER.email}

        result = connection_in_subscription(REQUEST_USER, CONNECTION_ID, cached_manager, dg_sp_manager)

        assert result is True
        cached_manager.insert_cached_user.assert_called_once_with({'email': REQUEST_USER.email})
        cached_manager.oc_id_exists.assert_called_once_with(
            seeded, REQUEST_USER.database, CachedOcIdType.CONNECTIONS, CONNECTION_ID,
        )
        dg_sp_manager.check_connection_in_sub.assert_not_called()

    def test_a_user_the_portal_does_not_know_is_refused_without_a_second_call(self) -> None:
        """No user anywhere means no subscription to hold the id - the portal is asked once, not twice."""
        cached_manager = MagicMock()
        cached_manager.get_cached_user.return_value = None
        dg_sp_manager = MagicMock()
        dg_sp_manager.get_dg_sp_user_data.return_value = None

        result = connection_in_subscription(REQUEST_USER, CONNECTION_ID, cached_manager, dg_sp_manager)

        assert result is False
        dg_sp_manager.get_dg_sp_user_data.assert_called_once_with(REQUEST_USER.email)
        dg_sp_manager.check_connection_in_sub.assert_not_called()
        cached_manager.insert_cached_user.assert_not_called()