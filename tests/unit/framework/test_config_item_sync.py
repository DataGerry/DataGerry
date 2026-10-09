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
Unit tests for cmdb.framework.config_item_sync

The per-type ConfigItem breakdown and the sync that sends it, with the managers and the service-portal manager
patched at the module path
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cmdb.framework.config_item_sync import build_type_object_counts, handle_sync_config_item_count
from cmdb.framework.config_item_sync_constants import ConfigItemTypeCountKey
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.config_item_sync'

NAME: str = ConfigItemTypeCountKey.NAME.value
COUNT: str = ConfigItemTypeCountKey.COUNT.value


class TestBuildTypeObjectCounts:
    """build_type_object_counts joins the per-type object counts with each CmdbType's label."""

    def test_maps_counts_to_type_labels(self) -> None:
        """Each counted type_id is resolved to its label and paired with the object count."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({1: 30, 2: 12}, 42)
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {
            1: SimpleNamespace(label='Server'),
            2: SimpleNamespace(label='Client'),
        }

        with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        assert type_counts == [{NAME: 'Server', COUNT: 30}, {NAME: 'Client', COUNT: 12}]
        assert total == 42

    def test_no_objects_returns_empty_without_type_lookup(self) -> None:
        """With no objects the helper returns [] and never queries the type lookup."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({}, 0)
        types_manager = MagicMock()

        with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        assert not type_counts
        assert total == 0
        types_manager.get_types_lookup.assert_not_called()

    def test_skips_type_missing_from_lookup(self) -> None:
        """A counted type_id whose CmdbType no longer exists is skipped, not emitted with no label."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({1: 30, 99: 5}, 35)
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {1: SimpleNamespace(label='Server')}

        with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        # the skipped type still counts toward the total the portal is told about
        assert type_counts == [{NAME: 'Server', COUNT: 30}]
        assert total == 35


class TestHandleSyncConfigItemCount:
    """handle_sync_config_item_count forwards the count plus the per-type breakdown to the portal."""

    def test_passes_count_and_type_breakdown_to_manager(self) -> None:
        """The built type-count list is passed straight into DgServicePortalManager.sync_config_items."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{NAME: 'Server', COUNT: 30}]

        with patch(f'{PATH}.build_type_object_counts', return_value=(type_counts, 30)), \
             patch(f'{PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user, 42)

        # an explicitly supplied count wins over the aggregation's total
        manager_instance.sync_config_items.assert_called_once_with(request_user, 42, type_counts)

    def test_derives_the_total_from_the_breakdown_when_no_count_is_given(self) -> None:
        """Omitting the count takes the total from the same aggregation - no extra full-collection count."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{NAME: 'Server', COUNT: 30}]

        with patch(f'{PATH}.build_type_object_counts', return_value=(type_counts, 31)), \
             patch(f'{PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user)

        manager_instance.sync_config_items.assert_called_once_with(request_user, 31, type_counts)


class TestTheWireKeys:
    """The portal reads these two names - pinned literally, so a renamed member cannot pass silently."""

    def test_the_breakdown_keys_are_name_and_count(self) -> None:
        """The service portal's contract"""
        assert (NAME, COUNT) == ('name', 'count')
