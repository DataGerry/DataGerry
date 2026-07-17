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
Unit tests for the shared ISMS route helpers in isms_routes_helper.

Pure tests driven against MagicMock managers: ``bulk_delete_reporting_in_use`` (delete_item reports
whether a document was removed) and ``update_multiple_items`` (the bulk-update orchestration that
resolves existing ids in one batched query and reports a per-item result).
"""
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import (
    bulk_delete_reporting_in_use,
    update_multiple_items,
)
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


def _existence_manager(existing_ids: list[int]) -> MagicMock:
    """Builds a MagicMock manager whose find_all returns docs for the given existing public_ids."""
    manager = MagicMock()
    manager.find_all.return_value = [{'public_id': public_id} for public_id in existing_ids]
    return manager


class TestUpdateMultipleItems:
    """``update_multiple_items`` batches the existence check and reports a per-item result."""

    def test_non_list_body_aborts_400(self) -> None:
        """A body that is not a list is rejected with HTTP 400."""
        with pytest.raises(HTTPException) as exc_info:
            update_multiple_items(MagicMock(), MagicMock(), {'public_id': ID_A}, "RiskClass", "tag")

        assert exc_info.value.code == 400

    def test_resolves_existence_in_one_query_without_per_item_get(self) -> None:
        """Existence is checked with a single batched find_all and never a per-item get_item (N+1 fix)."""
        manager = _existence_manager([ID_A, ID_B])

        update_multiple_items(
            manager, MagicMock(), [{'public_id': ID_A}, {'public_id': ID_B}], "RiskClass", "tag"
        )

        manager.find_all.assert_called_once_with(criteria={'public_id': {'$in': [ID_A, ID_B]}})
        manager.get_item.assert_not_called()

    def test_reports_per_item_status(self) -> None:
        """Existing ids update and succeed; a missing id and an id-less item both fail."""
        manager = _existence_manager([ID_A])
        model = MagicMock()

        results = update_multiple_items(
            manager, model,
            [{'public_id': ID_A}, {'public_id': MISSING_ID}, {'name': 'no id'}],
            "RiskClass", "tag",
        )

        by_id = {entry['public_id']: entry['status'] for entry in results}
        assert by_id == {ID_A: 'success', MISSING_ID: 'failed', None: 'failed'}
        # update_item runs only for the existing id
        manager.update_item.assert_called_once_with(ID_A, model.from_data.return_value)

    def test_no_public_ids_skips_find_all(self) -> None:
        """When no item carries a public_id, the existence query is skipped entirely."""
        manager = MagicMock()

        results = update_multiple_items(manager, MagicMock(), [{'name': 'no id'}], "RiskClass", "tag")

        manager.find_all.assert_not_called()
        assert results == [{'public_id': None, 'status': 'failed', 'message': 'Missing public_id'}]

    def test_update_failure_is_isolated_per_item(self) -> None:
        """An update_item raising for one id fails only that item; the rest still succeed."""
        manager = _existence_manager([ID_A, ID_B])

        def _fail_on_a(public_id: int, _data: object) -> None:
            if public_id == ID_A:
                raise RuntimeError('boom')

        manager.update_item.side_effect = _fail_on_a

        results = update_multiple_items(
            manager, MagicMock(), [{'public_id': ID_A}, {'public_id': ID_B}], "RiskClass", "tag"
        )

        by_id = {entry['public_id']: entry['status'] for entry in results}
        assert by_id == {ID_A: 'failed', ID_B: 'success'}
