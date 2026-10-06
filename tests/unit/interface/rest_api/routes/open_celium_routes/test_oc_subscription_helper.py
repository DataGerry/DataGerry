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
Unit tests for oc_subscription_helper: the cache read with its one portal seed, and the shared OpenCelium id check

Both managers are MagicMocks. ``read_or_seed_cached_user`` asks the portal only on a miss and seeds the cache once;
``oc_id_in_subscription`` answers a user neither the cache nor the portal knows with False, without a second portal
call - the check the connector, connection and scheduler routes share
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.open_celium import CachedOcIdType
from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.interface.rest_api.routes.open_celium_routes.oc_subscription_helper import (
    oc_id_in_subscription,
    read_or_seed_cached_user,
)
# -------------------------------------------------------------------------------------------------------------------- #

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='tenant_db', email='user@test.com')
OC_ID: int = 17
PORTAL_USER: dict[str, Any] = {'email': REQUEST_USER.email, 'subscriptions': []}
STORED_USER: dict[str, Any] = {'email': REQUEST_USER.email, 'subscriptions': [], 'public_id': 3}


class TestReadOrSeedCachedUser:
    """The cache first; the portal once, on a miss"""

    def test_a_hit_asks_no_portal(self) -> None:
        """The cached entry is returned as read"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.return_value = STORED_USER

        assert read_or_seed_cached_user(cached_manager, dg_sp_manager, REQUEST_USER.email) is STORED_USER
        dg_sp_manager.get_dg_sp_user_data.assert_not_called()
        cached_manager.insert_cached_user.assert_not_called()

    def test_a_miss_is_seeded_and_the_stored_entry_returned(self) -> None:
        """The portal's data is inserted, then read back - so the id and creation time come with it"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.side_effect = [None, STORED_USER]
        dg_sp_manager.get_dg_sp_user_data.return_value = PORTAL_USER

        assert read_or_seed_cached_user(cached_manager, dg_sp_manager, REQUEST_USER.email) is STORED_USER
        dg_sp_manager.get_dg_sp_user_data.assert_called_once_with(REQUEST_USER.email)
        cached_manager.insert_cached_user.assert_called_once_with(PORTAL_USER)

    @pytest.mark.parametrize('portal_answer', [None, {}], ids=['none', 'empty'])
    def test_a_user_the_portal_has_no_data_for_is_none_and_not_stored(self, portal_answer: Any) -> None:
        """Nothing is seeded from an empty answer"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.return_value = None
        dg_sp_manager.get_dg_sp_user_data.return_value = portal_answer

        assert read_or_seed_cached_user(cached_manager, dg_sp_manager, REQUEST_USER.email) is None
        cached_manager.insert_cached_user.assert_not_called()

    def test_a_portal_error_reaches_the_caller(self) -> None:
        """The portal's error status is not read as 'unknown user' - the route decides how to answer it"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.return_value = None
        failure = DgServicePortalGetError('portal down')
        dg_sp_manager.get_dg_sp_user_data.side_effect = failure

        with pytest.raises(DgServicePortalGetError) as exc_info:
            read_or_seed_cached_user(cached_manager, dg_sp_manager, REQUEST_USER.email)

        assert exc_info.value is failure
        cached_manager.insert_cached_user.assert_not_called()


class TestOcIdInSubscription:
    """One id check for every OpenCelium id kind"""

    @pytest.mark.parametrize('id_type', list(CachedOcIdType), ids=lambda kind: kind.name)
    @pytest.mark.parametrize('listed', [True, False], ids=['listed', 'not-listed'])
    def test_a_cached_user_is_answered_from_the_id_list(self, id_type: CachedOcIdType, listed: bool) -> None:
        """The id is looked up in the user's database's subscription, for each id kind"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.return_value = STORED_USER
        cached_manager.oc_id_exists.return_value = listed

        assert oc_id_in_subscription(REQUEST_USER, id_type, OC_ID, cached_manager, dg_sp_manager) is listed
        cached_manager.oc_id_exists.assert_called_once_with(STORED_USER, REQUEST_USER.database, id_type, OC_ID)
        dg_sp_manager.get_dg_sp_user_data.assert_not_called()

    def test_a_user_nobody_knows_is_false_after_one_portal_call(self) -> None:
        """No subscription can hold the id; the portal's per-kind check is never asked"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.get_cached_user.return_value = None
        dg_sp_manager.get_dg_sp_user_data.return_value = None

        assert oc_id_in_subscription(
            REQUEST_USER, CachedOcIdType.SCHEDULERS, OC_ID, cached_manager, dg_sp_manager,
        ) is False
        assert dg_sp_manager.method_calls == [
            ('get_dg_sp_user_data', (REQUEST_USER.email,), {}),
        ]
        cached_manager.oc_id_exists.assert_not_called()

    def test_a_passed_entry_is_used_as_is(self) -> None:
        """A resolved cached_user skips the cache read and the portal"""
        cached_manager, dg_sp_manager = MagicMock(), MagicMock()
        cached_manager.oc_id_exists.return_value = True

        assert oc_id_in_subscription(
            REQUEST_USER, CachedOcIdType.CONNECTORS, OC_ID, cached_manager, dg_sp_manager, STORED_USER,
        ) is True
        cached_manager.get_cached_user.assert_not_called()
        dg_sp_manager.get_dg_sp_user_data.assert_not_called()
