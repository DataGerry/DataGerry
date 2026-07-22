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
Unit tests for cmdb.framework.importer.importers.object_importer

DB-free: the importer methods run on a MagicMock-typed ``self`` with ``current_app`` / the
portal-sync helper patched at the module path. Focus: the ConfigItem count is synced to the
Service Portal ONCE per import batch (not per object) and only when the batch actually wrote
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.importer.importers.object_importer'


def _run_config(overwrite_public: bool = True) -> SimpleNamespace:
    """A minimal run config: import the whole list from the start."""
    return SimpleNamespace(start_element=0, max_elements=0, overwrite_public=overwrite_public)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        _import batch config-item sync                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestImportSyncsConfigItemCountOncePerBatch:
    """The N+1 fix: one portal sync for the whole import, not one per imported object."""

    def test_multi_object_batch_syncs_exactly_once(self) -> None:
        """Importing three new objects in cloud mode triggers a single config-item sync."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self.check_config_item_limit_reached.return_value = False
        # Every id lookup misses -> each object takes the insert-new branch
        mock_self.objects_manager.get_object.side_effect = ObjectsManagerGetError("not found")
        mock_self.objects_manager.get_new_object_public_id.side_effect = [101, 102, 103]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            ObjectImporter._import(mock_self, [{}, {}, {}])  # pylint: disable=protected-access

        mock_self._sync_config_item_count.assert_called_once()  # pylint: disable=protected-access

    def test_no_write_does_not_sync(self) -> None:
        """A batch that writes nothing (rejected id) does not contact the portal at all."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(overwrite_public=False)

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            # public_id present but overwrite disabled -> rejected before any DB write
            result = ObjectImporter._import(mock_self, [{'public_id': 5}])  # pylint: disable=protected-access

        mock_self._sync_config_item_count.assert_not_called()  # pylint: disable=protected-access
        assert len(result.failed_imports) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _import response message                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestImportResponseMessage:
    """The response message reports the real number of successful imports (was hard-coded 0)."""

    def test_message_reports_successful_import_count(self) -> None:
        """Importing three new objects yields 'Import of 3 objects' and three success entries."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self.check_config_item_limit_reached.return_value = False
        mock_self.objects_manager.get_object.side_effect = ObjectsManagerGetError("not found")
        mock_self.objects_manager.get_new_object_public_id.side_effect = [101, 102, 103]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, [{}, {}, {}])  # pylint: disable=protected-access

        assert len(result.success_imports) == 3
        assert result.message == 'Import of 3 objects'


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _sync_config_item_count                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyncConfigItemCount:
    """The batch-sync helper reports the current total once and is best-effort."""

    def test_reports_current_count_once(self) -> None:
        """It forwards a single fresh count_documents() total to the portal helper."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 42

        with patch(f'{PATH}.handle_sync_config_item_count') as sync:
            ObjectImporter._sync_config_item_count(mock_self)  # pylint: disable=protected-access

        sync.assert_called_once_with(mock_self.request_user, 42)

    def test_swallows_sync_errors(self) -> None:
        """A portal/transport failure is logged and swallowed, never raised into the import."""
        mock_self = MagicMock()

        with patch(f'{PATH}.handle_sync_config_item_count', side_effect=RuntimeError("boom")):
            ObjectImporter._sync_config_item_count(mock_self)  # pylint: disable=protected-access  # must not raise
