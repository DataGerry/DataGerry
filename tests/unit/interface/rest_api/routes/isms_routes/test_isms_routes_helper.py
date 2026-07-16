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
Unit tests for cmdb ... isms_routes.isms_routes_helper.bulk_delete_reporting_in_use

Pure tests: the shared ISMS bulk-delete orchestration is driven against a MagicMock manager whose
delete_item returns whether a document was actually removed. Verifies in-use ids are never deleted,
non-existent ids are not reported as deleted, and both result lists come back sorted.
"""
from unittest.mock import MagicMock

from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import bulk_delete_reporting_in_use
# -------------------------------------------------------------------------------------------------------------------- #

ID_A: int = 11
ID_B: int = 12
ID_C: int = 13
MISSING_ID: int = 99


class TestBulkDeleteReportingInUse:
    """``bulk_delete_reporting_in_use`` deletes the unused subset and reports both lists sorted."""

    def test_deletes_unused_skips_in_use(self) -> None:
        """In-use ids are never passed to delete_item; the rest are deleted and both lists sorted."""
        manager = MagicMock()
        manager.delete_item.return_value = True

        result = bulk_delete_reporting_in_use(manager, [ID_C, ID_A, ID_B], {ID_B})

        deleted_calls = [call.args[0] for call in manager.delete_item.call_args_list]
        assert ID_B not in deleted_calls
        assert result == {'successfully': [ID_A, ID_C], 'in_use': [ID_B]}

    def test_non_existent_id_not_reported_deleted(self) -> None:
        """delete_item returning False (missing doc) keeps that id out of the deleted list."""
        manager = MagicMock()
        manager.delete_item.side_effect = lambda public_id: public_id == ID_A

        result = bulk_delete_reporting_in_use(manager, [ID_A, MISSING_ID], set())

        assert result == {'successfully': [ID_A], 'in_use': []}

    def test_all_in_use_deletes_nothing(self) -> None:
        """When every requested id is in use, delete_item is never called."""
        manager = MagicMock()

        result = bulk_delete_reporting_in_use(manager, [ID_A, ID_B], {ID_A, ID_B})

        manager.delete_item.assert_not_called()
        assert result == {'successfully': [], 'in_use': [ID_A, ID_B]}

    def test_mixed_deleted_in_use_and_missing(self) -> None:
        """One batch with an unused-existing (A), an in-use (B) and an unused-missing (C) id partitions cleanly."""
        manager = MagicMock()
        # A exists and is deleted; C is unused but does not exist (delete_item returns False)
        manager.delete_item.side_effect = lambda public_id: public_id == ID_A

        result = bulk_delete_reporting_in_use(manager, [ID_A, ID_B, ID_C], {ID_B})

        # B (in-use) is never deleted; C (missing) is attempted but not reported; only A lands in successfully
        assert ID_B not in [call.args[0] for call in manager.delete_item.call_args_list]
        assert result == {'successfully': [ID_A], 'in_use': [ID_B]}
