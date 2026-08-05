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
Unit tests for cmdb.manager.system_manager.dg_service_portal_manager

DB-free: methods are invoked on a MagicMock-typed ``self`` and the module-level ``current_app``
and ``time`` are patched. Covers the enriched sync_config_items payload (config item count +
timestamp + per-type breakdown), the local-mode short-circuit, the failure branches, and the
millisecond current_timestamp helper
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cmdb.manager.system_manager.dg_service_portal_manager import (
    DgServicePortalManager,
    SYNC_CONFIG_ITEMS_URL,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.manager.system_manager.dg_service_portal_manager'

USER_EMAIL: str = 'user@acme.com'
USER_DATABASE: str = 'db_acme'
CONFIG_ITEM_COUNT: int = 42
FIXED_TIMESTAMP_MS: int = 1751932800000
TYPE_COUNTS: list[dict[str, object]] = [
    {'name': 'Server', 'count': 30},
    {'name': 'Client', 'count': 12},
]


def _request_user() -> SimpleNamespace:
    """A stand-in CmdbUser exposing only the email + database attributes the method reads."""
    return SimpleNamespace(email=USER_EMAIL, database=USER_DATABASE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                current_timestamp                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCurrentTimestamp:
    """current_timestamp returns the Unix time in milliseconds as an int."""

    def test_returns_milliseconds_as_int(self) -> None:
        """The seconds-based clock value is converted to a 13-digit millisecond integer."""
        with patch(f'{PATH}.time', return_value=1751932800.123):
            result = DgServicePortalManager.current_timestamp()

        assert result == 1751932800123
        assert isinstance(result, int)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                sync_config_items                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyncConfigItems:
    """sync_config_items ships the enriched payload in cloud mode and short-circuits in local mode."""

    def test_local_mode_returns_true_without_request(self) -> None:
        """In local mode the method returns True and never contacts the Service Portal."""
        mock_self = MagicMock()

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = True

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is True
        mock_self.sp_post.assert_not_called()

    def test_sends_enriched_payload_and_returns_true_on_success(self) -> None:
        """A cloud-mode call posts email/db/count plus timestamp and the per-type breakdown."""
        mock_self = MagicMock()
        mock_self.current_timestamp.return_value = FIXED_TIMESTAMP_MS
        mock_self.is_valid_response.return_value = True

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is True
        target, payload = mock_self.sp_post.call_args.args
        assert target == SYNC_CONFIG_ITEMS_URL
        assert payload == {
            'email': USER_EMAIL,
            'database_name': USER_DATABASE,
            'config_item_count': CONFIG_ITEM_COUNT,
            'timestamp': FIXED_TIMESTAMP_MS,
            'types': TYPE_COUNTS,
        }

    def test_returns_false_on_invalid_response(self) -> None:
        """A non-2xx Service Portal response makes the method return False."""
        mock_self = MagicMock()
        mock_self.is_valid_response.return_value = False

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is False

    def test_returns_false_when_request_raises(self) -> None:
        """A transport error is swallowed and reported as a failed sync (False)."""
        mock_self = MagicMock()
        mock_self.sp_post.side_effect = RuntimeError('boom')

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is False
