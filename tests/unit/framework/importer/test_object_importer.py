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

DB-free: the importer methods run on a MagicMock-typed ``self`` with ``current_app`` / the portal-sync
helper patched at the module path. Covers the batch loop (``_import``: success/reject/failure routing,
start_element + max_elements bounds, one-sync-per-batch) and the per-object write (``_import_single_object``:
new-id assignment, overwrite of an existing object, and the cloud ConfigItem limit).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #
# The suite drives the class-under-test's protected methods directly on a MagicMock ``self``
# pylint: disable=protected-access

PATH: str = 'cmdb.framework.importer.importers.object_importer'


def _run_config(start_element: int = 0, max_elements: int = 0, overwrite_public: bool = True) -> SimpleNamespace:
    """A minimal run config for the import loop."""
    return SimpleNamespace(
        start_element=start_element,
        max_elements=max_elements,
        overwrite_public=overwrite_public,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     _import                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def _candidates(count: int) -> list:
    """A list of (provided, generated) candidate pairs of empty objects (pass validation as-is)."""
    return [({}, {}) for _ in range(count)]


class TestToProvidedJson:
    """The base provided-data snapshot (used by JSON, whose entry is already the object)."""

    def test_deep_copies_the_entry(self) -> None:
        """It returns a deep copy so later coercion of the entry can't mutate the report snapshot."""
        entry = {'active': True, 'fields': [{'name': 'f', 'value': 'v'}]}

        result = ObjectImporter._to_provided_json(MagicMock(), entry)  # pylint: disable=protected-access

        assert result == entry
        assert result is not entry
        assert result['fields'] is not entry['fields']


class TestImportBatch:
    """The batch loop normalizes+validates, routes objects to success/failure and syncs once."""

    def test_message_and_success_count(self) -> None:
        """Three importable objects yield three successes and 'Import of 3 objects'."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._import_single_object.side_effect = [101, 102, 103]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(3), None)  # pylint: disable=protected-access

        assert len(result.success_imports) == 3
        assert not result.failed_imports
        assert result.message == 'Import of 3 objects'

    def test_multi_object_batch_syncs_exactly_once(self) -> None:
        """Importing several objects in cloud mode triggers a single config-item sync."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._import_single_object.side_effect = [101, 102, 103]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            ObjectImporter._import(mock_self, _candidates(3), None)  # pylint: disable=protected-access

        mock_self._sync_config_item_count.assert_called_once()  # pylint: disable=protected-access

    def test_invalid_object_is_rejected_without_writing(self) -> None:
        """A validation error (invalid active) rejects the object; nothing is written."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            result = ObjectImporter._import(  # pylint: disable=protected-access
                mock_self, [({'active': 'maybe'}, {'active': 'maybe'})], None)

        mock_self._import_single_object.assert_not_called()  # pylint: disable=protected-access
        mock_self._sync_config_item_count.assert_not_called()  # pylint: disable=protected-access
        assert len(result.failed_imports) == 1
        assert result.failed_imports[0].failed_object == {'active': 'maybe'}
        assert result.failed_imports[0].errors == ["Invalid value for 'active': 'maybe'"]

    def test_public_id_without_overwrite_is_rejected(self) -> None:
        """A public_id present with overwrite disabled is rejected before any write."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(overwrite_public=False)

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            result = ObjectImporter._import(  # pylint: disable=protected-access
                mock_self, [({'public_id': 5}, {'public_id': 5})], None)

        mock_self._sync_config_item_count.assert_not_called()  # pylint: disable=protected-access
        mock_self._import_single_object.assert_not_called()  # pylint: disable=protected-access
        assert len(result.failed_imports) == 1
        assert 'overwrit' in result.failed_imports[0].errors[0]

    def test_write_failure_is_recorded_as_failed(self) -> None:
        """An ObjectsManager* error from the per-object write becomes a failed import."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._import_single_object.side_effect = ObjectsManagerInsertError("boom")

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, [({'x': 1}, {})], None)  # pylint: disable=protected-access

        assert not result.success_imports
        assert len(result.failed_imports) == 1
        assert result.failed_imports[0].failed_object == {'x': 1}
        assert result.failed_imports[0].errors == ['boom']
        mock_self._sync_config_item_count.assert_not_called()  # pylint: disable=protected-access

    def test_start_element_skips_leading_objects(self) -> None:
        """start_element offsets the first processed object."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(start_element=2)
        mock_self._import_single_object.side_effect = [201]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(3), None)  # pylint: disable=protected-access

        # Only the 3rd object is processed
        assert len(result.success_imports) == 1
        assert mock_self._import_single_object.call_count == 1  # pylint: disable=protected-access

    def test_max_elements_limits_the_batch(self) -> None:
        """max_elements caps the number of processed objects (count, not absolute index)."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(start_element=1, max_elements=2)
        mock_self._import_single_object.side_effect = [301, 302]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(5), None)  # pylint: disable=protected-access

        # From index 1, at most 2 objects -> exactly 2 processed
        assert len(result.success_imports) == 2
        assert mock_self._import_single_object.call_count == 2  # pylint: disable=protected-access


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _import_single_object                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImportSingleObject:
    """The per-object write: new-id assignment, overwrite, and the cloud limit."""

    def test_new_object_gets_a_fresh_id_and_is_inserted(self) -> None:
        """An object without a public_id is assigned a new id, then inserted."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_new_object_public_id.return_value = 500
        obj: dict = {}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 500
        assert obj['public_id'] == 500
        # A new object never probes for an existing one
        mock_self.objects_manager.get_object.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_existing_object_is_overwritten(self) -> None:
        """An object with an existing public_id is deleted then re-inserted (lifecycle fields owned upstream)."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = {'creation_time': 'ORIGINAL'}
        obj: dict = {'public_id': 7}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 7
        # creation_time is forced by the normalization step, not preserved here
        assert 'creation_time' not in obj
        mock_self.objects_manager.delete_with_follow_up.assert_called_once_with(7, mock_self.request_user)
        mock_self.objects_manager.get_new_object_public_id.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_given_id_that_does_not_exist_is_inserted_as_is(self) -> None:
        """A supplied public_id with no existing object is inserted without deletion."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = None
        obj: dict = {'public_id': 9}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 9
        mock_self.objects_manager.delete_with_follow_up.assert_not_called()
        mock_self.objects_manager.get_new_object_public_id.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_cloud_limit_reached_raises_before_insert(self) -> None:
        """In cloud mode a reached ConfigItem limit raises and skips the insert."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_new_object_public_id.return_value = 1
        mock_self.check_config_item_limit_reached.return_value = True

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            with pytest.raises(ObjectsManagerInsertError):
                ObjectImporter._import_single_object(mock_self, {})  # pylint: disable=protected-access

        mock_self.objects_manager.insert_object.assert_not_called()

    def test_get_error_propagates(self) -> None:
        """A DB error probing for the existing object propagates (caught as a failed import upstream)."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.side_effect = ObjectsManagerGetError("db down")

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            with pytest.raises(ObjectsManagerGetError):
                ObjectImporter._import_single_object(mock_self, {'public_id': 3})  # pylint: disable=protected-access

    def test_delete_error_propagates(self) -> None:
        """A delete failure while overwriting propagates."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = {'creation_time': 'X'}
        mock_self.objects_manager.delete_with_follow_up.side_effect = ObjectsManagerDeleteError("nope")

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            with pytest.raises(ObjectsManagerDeleteError):
                ObjectImporter._import_single_object(mock_self, {'public_id': 3})  # pylint: disable=protected-access


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _sync_config_item_count                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestAbstractMethods:
    """generate_object and start_import must be implemented by concrete importers."""

    def test_generate_object_is_abstract(self) -> None:
        """The base generate_object raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.generate_object(MagicMock(), {})

    def test_start_import_is_abstract(self) -> None:
        """The base start_import raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.start_import(MagicMock())


class TestConfigItemLimit:
    """The cloud ConfigItem limit check compares the object count against the user's limit."""

    def test_limit_reached_when_count_at_limit(self) -> None:
        """At or above the user's limit the check reports True."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 10
        user = SimpleNamespace(config_items_limit=10)

        assert ObjectImporter.check_config_item_limit_reached(mock_self, user) is True

    def test_limit_not_reached_below_limit(self) -> None:
        """Below the user's limit the check reports False."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 3
        user = SimpleNamespace(config_items_limit=10)

        assert ObjectImporter.check_config_item_limit_reached(mock_self, user) is False


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
