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
Unit tests for the CmdbRelation route helpers

Pure tests: the ObjectRelationsManager / ObjectRelationLogsManager are MagicMocks, so only the
comparison logic, the delete-cascade dispatch and the log orchestration are exercised.
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.log_model import LogInteraction
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerBuildError
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    resolve_counterpart_summaries,
    get_deleted_type_ids,
    handle_deleted_type_ids,
    get_existing_relation_or_abort,
    validate_object_relation_endpoints,
    log_object_relation_change,
    log_object_relation_update,
    log_object_relation_deletions,
)
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_PUBLIC_ID: int = 5

PARENT_TYPE_A: int = 1
PARENT_TYPE_B: int = 2
CHILD_TYPE_A: int = 3
CHILD_TYPE_B: int = 4


def _relation(public_id: int, parent_ids: list[int], child_ids: list[int]) -> dict[str, Any]:
    """Builds the minimal relation dict the helper reads."""
    return {'public_id': public_id, 'parent_type_ids': parent_ids, 'child_type_ids': child_ids}


# ----------------------------------------------------- get_deleted_type_ids ----------------------------------------- #

class TestGetDeletedTypeIds:
    """Tests for get_deleted_type_ids (pure set difference)."""

    def test_returns_ids_only_in_old(self) -> None:
        """IDs present in old but not in new are returned."""
        assert set(get_deleted_type_ids([1, 2, 3], [2, 3])) == {1}

    def test_returns_empty_when_nothing_removed(self) -> None:
        """No removed ids yields an empty list."""
        assert get_deleted_type_ids([1, 2], [1, 2, 3]) == []


# --------------------------------------------------- handle_deleted_type_ids ---------------------------------------- #

class TestHandleDeletedTypeIds:
    """Tests for handle_deleted_type_ids (cascade dispatch to ObjectRelationsManager)."""

    def test_deletes_object_relations_for_removed_parent_and_child(self) -> None:
        """Removing a parent and a child type triggers one cascade call each (parent flag True/False)."""
        manager = MagicMock()
        old_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A, PARENT_TYPE_B], [CHILD_TYPE_A, CHILD_TYPE_B])
        new_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])

        handle_deleted_type_ids(old_relation, new_relation, manager)

        assert manager.delete_invalidated_object_relations.call_count == 2
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [PARENT_TYPE_B], True)
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [CHILD_TYPE_B], False)

    def test_no_cascade_when_nothing_removed(self) -> None:
        """When no parent/child types are removed, no cascade call is made."""
        manager = MagicMock()
        relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])

        handle_deleted_type_ids(relation, dict(relation), manager)

        manager.delete_invalidated_object_relations.assert_not_called()


# ------------------------------------------------ get_existing_relation_or_abort ------------------------------------ #

class TestGetExistingRelationOrAbort:
    """get_existing_relation_or_abort returns the relation or aborts 400."""

    def test_returns_relation_when_present(self) -> None:
        """An existing relation is returned unchanged."""
        relations_manager = MagicMock()
        relation = {'public_id': RELATION_PUBLIC_ID}
        relations_manager.get_relation.return_value = relation

        assert get_existing_relation_or_abort(relations_manager, RELATION_PUBLIC_ID) is relation
        relations_manager.get_relation.assert_called_once_with(RELATION_PUBLIC_ID)

    def test_aborts_400_when_missing(self) -> None:
        """A missing relation aborts with 400."""
        relations_manager = MagicMock()
        relations_manager.get_relation.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_existing_relation_or_abort(relations_manager, RELATION_PUBLIC_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# --------------------------------------------- validate_object_relation_endpoints ---------------------------------- #

class TestValidateObjectRelationEndpoints:
    """validate_object_relation_endpoints guards distinct, present parent/child objects."""

    def test_passes_for_distinct_endpoints(self) -> None:
        """Distinct, present parent and child ids do not abort."""
        validate_object_relation_endpoints(1, 2)

    @pytest.mark.parametrize('parent_id, child_id', [(None, 2), (1, None), (None, None), (0, 2)])
    def test_aborts_400_when_endpoint_missing(self, parent_id: int | None, child_id: int | None) -> None:
        """A missing parent or child id aborts with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_relation_endpoints(parent_id, child_id)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_aborts_400_when_parent_equals_child(self) -> None:
        """The same object as parent and child aborts with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_relation_endpoints(7, 7)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------ the log helpers --------------------------------------------------- #

OLD_RELATION: dict[str, Any] = {'public_id': 11, 'relation_parent_id': 1, 'relation_child_id': 2}
NEW_RELATION: dict[str, Any] = {'public_id': 11, 'relation_parent_id': 1, 'relation_child_id': 2}
MOVED_RELATION: dict[str, Any] = {'public_id': 11, 'relation_parent_id': 1, 'relation_child_id': 9}

REQUEST_USER = MagicMock(name='request_user')


def _logs_manager(endpoints_changed: bool = False) -> MagicMock:
    """Builds a logs-manager mock whose endpoint comparison returns the given verdict."""
    logs_manager = MagicMock()
    logs_manager.check_related_object_changed.return_value = endpoints_changed

    return logs_manager


class TestLogObjectRelationChange:
    """log_object_relation_change writes one log and never lets a logging failure escape."""

    def test_writes_the_log(self) -> None:
        """The interaction and both states are handed to the logs manager unchanged."""
        logs_manager = _logs_manager()

        log_object_relation_change(logs_manager, REQUEST_USER, LogInteraction.CREATE, None, NEW_RELATION)

        logs_manager.build_object_relation_log.assert_called_once_with(
            LogInteraction.CREATE, REQUEST_USER, None, NEW_RELATION,
        )

    def test_swallows_a_logging_failure(self) -> None:
        """A build/insert error is logged and dropped - the write it describes already happened."""
        logs_manager = _logs_manager()
        logs_manager.build_object_relation_log.side_effect = ObjectRelationLogsManagerBuildError('boom')

        log_object_relation_change(logs_manager, REQUEST_USER, LogInteraction.DELETE, OLD_RELATION, None)


class TestLogObjectRelationUpdate:
    """log_object_relation_update records a field edit differently from a moved relation."""

    def test_field_only_change_is_one_edit(self) -> None:
        """Unchanged endpoints yield a single EDIT entry."""
        logs_manager = _logs_manager(endpoints_changed=False)

        log_object_relation_update(logs_manager, REQUEST_USER, OLD_RELATION, NEW_RELATION)

        logs_manager.build_object_relation_log.assert_called_once_with(
            LogInteraction.EDIT, REQUEST_USER, OLD_RELATION, NEW_RELATION,
        )

    def test_moved_relation_is_a_delete_plus_a_create(self) -> None:
        """A changed endpoint is recorded as the old relation's DELETE and the new one's CREATE."""
        logs_manager = _logs_manager(endpoints_changed=True)

        log_object_relation_update(logs_manager, REQUEST_USER, OLD_RELATION, MOVED_RELATION)

        assert [call.args[0] for call in logs_manager.build_object_relation_log.call_args_list] == [
            LogInteraction.DELETE, LogInteraction.CREATE,
        ]
        assert logs_manager.build_object_relation_log.call_args_list[0].args[2] is OLD_RELATION
        assert logs_manager.build_object_relation_log.call_args_list[1].args[3] is MOVED_RELATION


class TestLogObjectRelationDeletions:
    """log_object_relation_deletions batches one DELETE log per deleted relation."""

    def test_reserves_ids_and_inserts_once(self) -> None:
        """N relations cost one id reservation and one insert, with the ids stamped onto the logs."""
        logs_manager = _logs_manager()
        logs_manager.format_object_relation_log_data.side_effect = [{'log': 'a'}, {'log': 'b'}]
        logs_manager.reserve_public_ids.return_value = [101, 102]

        log_object_relation_deletions(logs_manager, REQUEST_USER, [OLD_RELATION, MOVED_RELATION])

        logs_manager.reserve_public_ids.assert_called_once_with(2)
        logs_manager.insert_many.assert_called_once_with(
            [{'log': 'a', 'public_id': 101}, {'log': 'b', 'public_id': 102}], skip_public=True,
        )

    def test_no_deletions_writes_nothing(self) -> None:
        """An empty selection reserves no ids and inserts nothing."""
        logs_manager = _logs_manager()

        log_object_relation_deletions(logs_manager, REQUEST_USER, [])

        logs_manager.reserve_public_ids.assert_not_called()
        logs_manager.insert_many.assert_not_called()

    def test_swallows_a_logging_failure(self) -> None:
        """A failure while batching the logs must not fail the delete that already happened."""
        logs_manager = _logs_manager()
        logs_manager.format_object_relation_log_data.side_effect = ObjectRelationLogsManagerBuildError('boom')

        log_object_relation_deletions(logs_manager, REQUEST_USER, [OLD_RELATION])

        logs_manager.insert_many.assert_not_called()


class TestResolveCounterpartSummaries:
    """resolve_counterpart_summaries only reads the objects it actually needs."""

    def test_no_ids_skips_the_read(self) -> None:
        """An empty page (or one with only unresolvable sides) costs no query at all."""
        objects_manager = MagicMock()

        assert resolve_counterpart_summaries([], MagicMock(), objects_manager) == {}
        objects_manager.iterate.assert_not_called()

    def test_only_none_ids_skips_the_read(self) -> None:
        """Rows whose counterpart id is missing do not trigger a read either."""
        objects_manager = MagicMock()

        assert resolve_counterpart_summaries([None, None], MagicMock(), objects_manager) == {}
        objects_manager.iterate.assert_not_called()
