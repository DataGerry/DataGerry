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

import pytest

from cmdb.framework.config_item_sync import (
    COUNT_READ_ERRORS,
    build_type_object_counts,
    handle_sync_config_item_count,
)
from cmdb.framework.config_item_sync_constants import ConfigItemTypeCountKey
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.security import NoAccessTokenError
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
    """handle_sync_config_item_count: hosted cloud only, best-effort, the total from the breakdown's aggregation."""

    @pytest.fixture(autouse=True)
    def _hosted(self):
        """Every case runs as a hosted cloud installation unless it says otherwise"""
        with patch(f'{PATH}.is_hosted_cloud', return_value=True) as hosted:
            yield hosted

    def test_reports_the_total_and_the_breakdown_of_one_aggregation(self) -> None:
        """No extra full-collection count: the total is the aggregation's"""
        request_user = MagicMock()
        type_counts = [{NAME: 'Server', COUNT: 30}]

        with patch(f'{PATH}.build_type_object_counts', return_value=(type_counts, 31)), \
             patch(f'{PATH}.DgServicePortalManager') as portal:
            handle_sync_config_item_count(request_user)

        portal.return_value.sync_config_items.assert_called_once_with(request_user, 31, type_counts)

    def test_off_a_hosted_cloud_nothing_is_read_or_sent(self, _hosted: MagicMock) -> None:
        """On-premise and on a developer's local cloud stack: no portal, no count"""
        _hosted.return_value = False

        with patch(f'{PATH}.build_type_object_counts') as counts, \
             patch(f'{PATH}.DgServicePortalManager') as portal:
            handle_sync_config_item_count(MagicMock())

        counts.assert_not_called()
        portal.assert_not_called()

    def test_a_missing_portal_configuration_skips_the_sync_before_counting(self, caplog) -> None:
        """The constructor's NoAccessTokenError is logged, and no count is read for nothing"""
        with patch(f'{PATH}.build_type_object_counts') as counts, \
             patch(f'{PATH}.DgServicePortalManager', side_effect=NoAccessTokenError('no token')):
            handle_sync_config_item_count(MagicMock())

        counts.assert_not_called()
        assert 'not configured, sync skipped' in caplog.text

    @pytest.mark.parametrize('failure', [
        ObjectsManagerIterationError('down'), TypesManagerGetError('down'),
        DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'),
    ], ids=['objects', 'types', 'network', 'lock'])
    def test_a_failed_count_read_skips_the_sync_without_failing_the_request(self, failure: Exception) -> None:
        """Telemetry reported after the write must not turn a committed write into an error"""
        with patch(f'{PATH}.build_type_object_counts', side_effect=failure), \
             patch(f'{PATH}.DgServicePortalManager') as portal:
            handle_sync_config_item_count(MagicMock())

        portal.return_value.sync_config_items.assert_not_called()

    def test_a_bug_while_counting_propagates_as_itself(self) -> None:
        """Only the database's failure is swallowed"""
        with patch(f'{PATH}.build_type_object_counts', side_effect=TypeError('bug')), \
             patch(f'{PATH}.DgServicePortalManager'):
            with pytest.raises(TypeError):
                handle_sync_config_item_count(MagicMock())

    def test_a_bug_while_building_the_portal_propagates_as_itself(self) -> None:
        """Only the missing configuration is the sync's to swallow"""
        with patch(f'{PATH}.DgServicePortalManager', side_effect=KeyError('bug')):
            with pytest.raises(KeyError):
                handle_sync_config_item_count(MagicMock())

    def test_the_count_read_errors_are_the_reads_and_the_transient_ones(self) -> None:
        """Pinned literally, so a narrowed tuple cannot pass silently"""
        assert set(COUNT_READ_ERRORS) == {
            ObjectsManagerIterationError, TypesManagerGetError, DocumentNetworkError, DocumentLockTimeoutError,
        }


class TestTheWireKeys:
    """The portal reads these two names - pinned literally, so a renamed member cannot pass silently."""

    def test_the_breakdown_keys_are_name_and_count(self) -> None:
        """The service portal's contract"""
        assert (NAME, COUNT) == ('name', 'count')
