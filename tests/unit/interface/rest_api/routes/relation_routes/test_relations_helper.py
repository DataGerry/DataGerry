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
from cmdb.models.relation_model import RelationDiffKey, RelationKey
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerBuildError
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    abort_if_object_relation_pair_duplicate,
    abort_if_object_relation_pair_taken,
    object_relation_pair,
    object_relation_pair_taken_message,
    resolve_counterpart_summaries,
    get_deleted_type_ids,
    handle_deleted_type_ids,
    get_added_and_removed_fields,
    get_retyped_fields,
    declared_field_names,
    declared_field_types,
    guard_relation_field_identifier_change,
    relation_field_identifier_change_blocker,
    validate_relation_type_ids,
    apply_relation_update,
    cascade_relation_update,
    reconcile_object_relations,
    get_existing_relation_or_abort,
    validate_object_relation_endpoints,
    log_object_relation_change,
    log_object_relation_update,
    log_object_relation_deletions,
    read_bulk_delete_selection,
    delete_object_relations,
)
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    MAX_BULK_DELETE_OBJECT_RELATIONS,
    OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE,
    OBJECT_RELATION_BULK_NO_IDS_MESSAGE,
    OBJECT_RELATION_BULK_TOO_MANY_MESSAGE,
    OBJECT_RELATION_PAIR_TAKEN_MESSAGE,
    RELATION_FIELD_IDENTIFIER_IMMUTABLE_MESSAGE,
    RELATION_INSTANCE_LOOKUP_FAILED_MESSAGE,
    BulkDeleteKey,
)
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentInsertError
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_PUBLIC_ID: int = 5
FORGED_PUBLIC_ID: int = 999

PARENT_TYPE_A: int = 1
PARENT_TYPE_B: int = 2
CHILD_TYPE_A: int = 3
CHILD_TYPE_B: int = 4
UNKNOWN_TYPE_ID: int = 77


def _relation(public_id: int, parent_ids: list[int], child_ids: list[int]) -> dict[str, Any]:
    """Builds the minimal relation dict the helper reads."""
    return {
        RelationKey.PUBLIC_ID.value: public_id,
        RelationKey.PARENT_TYPE_IDS.value: parent_ids,
        RelationKey.CHILD_TYPE_IDS.value: child_ids,
    }


def _relation_declaring(*field_names: str, sectioned: list[str] | None = None) -> dict[str, Any]:
    """A relation dict declaring the given fields; one section shows `sectioned` (all of them by default)."""
    shown: list[str] = list(field_names) if sectioned is None else sectioned

    return {
        RelationKey.FIELDS.value: [{'name': name, 'type': 'text', 'label': name.upper()} for name in field_names],
        RelationKey.SECTIONS.value: [{'name': 's1', RelationKey.FIELDS.value: shown}],
    }


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
        deleted: list[dict[str, Any]] = []

        handle_deleted_type_ids(RELATION_PUBLIC_ID, old_relation, new_relation, manager, deleted)

        assert manager.delete_invalidated_object_relations.call_count == 2
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [PARENT_TYPE_B], True, deleted)
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [CHILD_TYPE_B], False, deleted)

    def test_no_cascade_when_nothing_removed(self) -> None:
        """When no parent/child types are removed, no cascade call is made."""
        manager = MagicMock()
        relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])

        handle_deleted_type_ids(RELATION_PUBLIC_ID, relation, dict(relation), manager, [])

        manager.delete_invalidated_object_relations.assert_not_called()

    def test_missing_type_lists_are_read_as_empty(self) -> None:
        """A stored relation without the type lists reports nothing removed instead of raising."""
        manager = MagicMock()

        handle_deleted_type_ids(RELATION_PUBLIC_ID, {}, {}, manager, [])

        manager.delete_invalidated_object_relations.assert_not_called()

    def test_type_lists_dropped_by_the_new_payload_are_removals(self) -> None:
        """Every previously allowed type counts as removed when the new payload carries no list."""
        manager = MagicMock()
        old_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])
        deleted: list[dict[str, Any]] = []

        handle_deleted_type_ids(RELATION_PUBLIC_ID, old_relation, {}, manager, deleted)

        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [PARENT_TYPE_A], True, deleted)
        manager.delete_invalidated_object_relations.assert_any_call(RELATION_PUBLIC_ID, [CHILD_TYPE_A], False, deleted)


# ------------------------------------------------ get_added_and_removed_fields -------------------------------------- #

class TestGetAddedAndRemovedFields:
    """get_added_and_removed_fields diffs the DECLARED fields - the names an instance may hold - not the sections"""

    def test_detects_added_and_removed_fields(self) -> None:
        """Declared only in new = 'added', only in old = 'removed', both sorted"""
        result = get_added_and_removed_fields(_relation_declaring('a', 'b', 'd'), _relation_declaring('b', 'e', 'c'))

        assert result == {RelationDiffKey.ADDED.value: ['c', 'e'], RelationDiffKey.REMOVED.value: ['a', 'd']}

    def test_no_change_yields_empty_lists(self) -> None:
        """Identical declarations produce empty added/removed lists."""
        relation = _relation_declaring('a', 'b')

        result = get_added_and_removed_fields(relation, dict(relation))

        assert result == {RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: []}

    def test_moving_a_declared_field_into_a_section_is_no_change(self) -> None:
        """The section diff called it 'added' and every instance got it a second time"""
        unsectioned = _relation_declaring('a', sectioned=[])
        sectioned = _relation_declaring('a', sectioned=['a'])

        assert get_added_and_removed_fields(unsectioned, sectioned) == {
            RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: [],
        }

    def test_taking_a_declared_field_out_of_every_section_is_no_change(self) -> None:
        """The section diff called it 'removed' and wiped a field the relation still declares"""
        sectioned = _relation_declaring('a', sectioned=['a'])
        unsectioned = _relation_declaring('a', sectioned=[])

        assert get_added_and_removed_fields(sectioned, unsectioned) == {
            RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: [],
        }

    def test_dropping_an_unsectioned_field_removes_it(self) -> None:
        """No section ever named it, so the section diff never removed its values"""
        result = get_added_and_removed_fields(_relation_declaring('a', 'b', sectioned=['a']),
                                              _relation_declaring('a', sectioned=['a']))

        assert result == {RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: ['b']}

    def test_missing_or_null_fields_are_treated_as_empty(self) -> None:
        """A relation without 'fields', or with None, declares nothing instead of raising"""
        result = get_added_and_removed_fields({}, {RelationKey.FIELDS.value: None})

        assert result == {RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: []}


class TestDeclaredFieldNames:
    """declared_field_names reads the flat `fields` list"""

    def test_reads_the_names_of_the_field_dicts(self) -> None:
        """Each declared field contributes its name"""
        assert declared_field_names(_relation_declaring('a', 'b')) == {'a', 'b'}

    @pytest.mark.parametrize('entry', [
        pytest.param('a', id='a bare string'),
        pytest.param({'label': 'A'}, id='no name'),
        pytest.param({'name': 7}, id='a non-string name'),
        pytest.param(None, id='None'),
    ])
    def test_an_entry_that_is_no_named_field_declares_nothing(self, entry: Any) -> None:
        """Stored data may predate the schema - it is skipped, not a crash"""
        assert declared_field_names({RelationKey.FIELDS.value: [entry, {'name': 'b'}]}) == {'b'}


# -------------------------------------------------- validate_relation_type_ids -------------------------------------- #

class TestValidateRelationTypeIds:
    """validate_relation_type_ids refuses relations referencing non-existent CmdbTypes."""

    def test_passes_when_every_type_exists(self) -> None:
        """A payload whose parent/child types all exist is accepted."""
        types_manager = MagicMock()
        types_manager.get_existing_type_ids.return_value = {PARENT_TYPE_A, CHILD_TYPE_A}

        validate_relation_type_ids(types_manager, _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A]))

        types_manager.get_existing_type_ids.assert_called_once_with([PARENT_TYPE_A, CHILD_TYPE_A])

    def test_aborts_400_and_names_the_unknown_ids(self) -> None:
        """An id no CmdbType carries aborts with 400 and is named in the message."""
        types_manager = MagicMock()
        types_manager.get_existing_type_ids.return_value = {PARENT_TYPE_A}

        with pytest.raises(HTTPException) as exc_info:
            validate_relation_type_ids(
                types_manager,
                _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [UNKNOWN_TYPE_ID]),
            )

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert str(UNKNOWN_TYPE_ID) in exc_info.value.description

    def test_skips_the_lookup_without_referenced_ids(self) -> None:
        """A payload carrying no type ids needs no existence query."""
        types_manager = MagicMock()

        validate_relation_type_ids(types_manager, {})

        types_manager.get_existing_type_ids.assert_not_called()


# ---------------------------------------------------- apply_relation_update ----------------------------------------- #

class TestApplyRelationUpdate:
    """apply_relation_update pins the identity, diffs the sections and persists the relation."""

    @staticmethod
    def _payload(public_id: int, *field_names: str) -> dict[str, Any]:
        """A CmdbRelation payload complete enough for CmdbRelation.from_data."""
        return {
            RelationKey.PUBLIC_ID.value: public_id,
            RelationKey.RELATION_NAME.value: 'r',
            RelationKey.PARENT_TYPE_IDS.value: [PARENT_TYPE_A],
            RelationKey.CHILD_TYPE_IDS.value: [CHILD_TYPE_A],
            RelationKey.RELATION_NAME_PARENT.value: 'is-parent-of',
            RelationKey.RELATION_NAME_CHILD.value: 'is-child-of',
            **_relation_declaring(*field_names),
        }

    def test_pins_the_public_id_to_the_route_argument(self) -> None:
        """A forged body public_id is overwritten by the one the route was called with."""
        relations_manager = MagicMock()

        data = self._payload(FORGED_PUBLIC_ID)
        relation, _ = apply_relation_update(RELATION_PUBLIC_ID, data, {}, relations_manager)

        assert data[RelationKey.PUBLIC_ID.value] == RELATION_PUBLIC_ID
        assert relation.get_public_id() == RELATION_PUBLIC_ID
        relations_manager.update_relation.assert_called_once_with(RELATION_PUBLIC_ID, relation)

    def test_returns_the_section_field_diff(self) -> None:
        """The diff is computed from the old document against the new payload."""
        _, changed_fields = apply_relation_update(
            RELATION_PUBLIC_ID,
            self._payload(RELATION_PUBLIC_ID, 'b'),
            _relation_declaring('a'),
            MagicMock(),
        )

        assert set(changed_fields[RelationDiffKey.ADDED.value]) == {'b'}
        assert set(changed_fields[RelationDiffKey.REMOVED.value]) == {'a'}
        assert changed_fields[RelationDiffKey.RETYPED.value] == []

    def test_the_diff_names_a_retyped_field(self) -> None:
        """A kept name with another type is reported for the reset"""
        new_payload: dict[str, Any] = self._payload(RELATION_PUBLIC_ID, 'a')
        new_payload[RelationKey.FIELDS.value][0]['type'] = 'date'

        _, changed_fields = apply_relation_update(RELATION_PUBLIC_ID, new_payload, _relation_declaring('a'),
                                                  MagicMock())

        assert changed_fields[RelationDiffKey.RETYPED.value] == ['a']


# --------------------------------------------------- cascade_relation_update ---------------------------------------- #

class TestCascadeRelationUpdate:
    """cascade_relation_update reconciles the dependent CmdbObjectRelations."""

    def test_deletes_invalidated_instances_and_applies_the_field_diff(self) -> None:
        """Both cascade steps run with the relation's public_id."""
        manager = MagicMock()
        old_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A, PARENT_TYPE_B], [CHILD_TYPE_A])
        new_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])
        changed_fields = {RelationDiffKey.ADDED.value: ['b'], RelationDiffKey.REMOVED.value: ['a']}

        deleted: list[dict[str, Any]] = []

        cascade_relation_update(RELATION_PUBLIC_ID, old_relation, new_relation, changed_fields, manager, deleted)

        manager.delete_invalidated_object_relations.assert_called_once_with(
            RELATION_PUBLIC_ID, [PARENT_TYPE_B], True, deleted,
        )
        manager.update_changed_fields.assert_called_once_with(RELATION_PUBLIC_ID, changed_fields)


# --------------------------------------------------- reconcile_object_relations ------------------------------------- #

class TestReconcileObjectRelations:
    """The relation update's cascade, with one DELETE history entry per instance it deleted"""

    @staticmethod
    def _removing_parent_b(objects_manager: MagicMock, logs_manager: MagicMock) -> int:
        """Runs the reconcile for an update that drops PARENT_TYPE_B and changes no section field."""
        old_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A, PARENT_TYPE_B], [CHILD_TYPE_A])
        new_relation = _relation(RELATION_PUBLIC_ID, [PARENT_TYPE_A], [CHILD_TYPE_A])
        changed_fields = {RelationDiffKey.ADDED.value: [], RelationDiffKey.REMOVED.value: []}

        return reconcile_object_relations(RELATION_PUBLIC_ID, old_relation, new_relation, changed_fields,
                                          objects_manager, logs_manager, MagicMock())

    @staticmethod
    def _deleting(*documents: dict[str, Any], then: Exception | None = None):
        """A delete_invalidated_object_relations stand-in that collects the documents, then raises `then`."""
        def _delete(_relation_id, _ids, _is_parent, deleted):
            deleted.extend(documents)
            if then is not None:
                raise then

        return _delete

    def test_answers_the_count_and_logs_each_deleted_instance(self) -> None:
        """Two instances deleted: the answer is 2 and one batch insert carries two DELETE logs"""
        objects_manager, logs_manager = MagicMock(), MagicMock()
        objects_manager.delete_invalidated_object_relations.side_effect = self._deleting(
            {'public_id': 31}, {'public_id': 32},
        )
        logs_manager.reserve_public_ids.return_value = [71, 72]

        assert self._removing_parent_b(objects_manager, logs_manager) == 2

        logs_manager.insert_many.assert_called_once()
        assert len(logs_manager.insert_many.call_args.args[0]) == 2
        assert [call.args[0] for call in logs_manager.format_object_relation_log_data.call_args_list] == [
            LogInteraction.DELETE, LogInteraction.DELETE,
        ]

    def test_nothing_deleted_writes_no_log(self) -> None:
        """No instance used the removed type: 0, and no history insert"""
        objects_manager, logs_manager = MagicMock(), MagicMock()
        objects_manager.delete_invalidated_object_relations.side_effect = self._deleting()

        assert self._removing_parent_b(objects_manager, logs_manager) == 0

        logs_manager.insert_many.assert_not_called()

    def test_a_failure_part_way_still_logs_what_was_deleted(self) -> None:
        """The error propagates (the route answers the partial application); the deleted one is in history"""
        objects_manager, logs_manager = MagicMock(), MagicMock()
        objects_manager.delete_invalidated_object_relations.side_effect = self._deleting(
            {'public_id': 31}, then=BaseManagerDeleteError('boom'),
        )
        logs_manager.reserve_public_ids.return_value = [71]

        with pytest.raises(BaseManagerDeleteError):
            self._removing_parent_b(objects_manager, logs_manager)

        assert len(logs_manager.insert_many.call_args.args[0]) == 1
        objects_manager.update_changed_fields.assert_not_called()


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                         read_bulk_delete_selection                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
TARGET_IDS: str = BulkDeleteKey.TARGET_IDS.value


def _refusal(body: Any) -> HTTPException:
    """The HTTPException the selection reader raises for a body"""
    with pytest.raises(HTTPException) as exc_info:
        read_bulk_delete_selection(body)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    return exc_info.value


class TestReadBulkDeleteSelection:
    """The bulk delete body: an object carrying a non-empty list of at most the limit's distinct ids"""

    def test_numbers_and_digit_strings_are_read_in_order(self) -> None:
        """Both JSON forms of an id, the order kept"""
        assert read_bulk_delete_selection({TARGET_IDS: [3, '1', 2]}) == [3, 1, 2]

    def test_duplicates_collapse_to_their_first_place(self) -> None:
        """An id named twice - also once as a string - is one id"""
        assert read_bulk_delete_selection({TARGET_IDS: [4, 2, '4', 4]}) == [4, 2]

    @pytest.mark.parametrize('body', [[1, 2], '12', 7, None], ids=['list', 'string', 'number', 'null'])
    def test_a_body_that_is_no_object_is_refused(self, body: Any) -> None:
        """It was read with .get - a 500"""
        assert _refusal(body).description == OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE.format(key=TARGET_IDS)

    @pytest.mark.parametrize('body', [{}, {TARGET_IDS: []}, {TARGET_IDS: None}], ids=['missing', 'empty', 'null'])
    def test_a_missing_selection_is_refused(self, body: dict[str, Any]) -> None:
        """Nothing named, nothing to delete"""
        assert _refusal(body).description == OBJECT_RELATION_BULK_NO_IDS_MESSAGE

    def test_a_string_selection_is_refused(self) -> None:
        """'12' would have been the ids 1 and 2"""
        _refusal({TARGET_IDS: '12'})

    def test_exactly_the_limit_is_accepted(self) -> None:
        """The boundary itself"""
        selection = list(range(1, MAX_BULK_DELETE_OBJECT_RELATIONS + 1))

        assert read_bulk_delete_selection({TARGET_IDS: selection}) == selection

    def test_one_past_the_limit_is_refused(self) -> None:
        """Named with the limit and the count"""
        selection = list(range(1, MAX_BULK_DELETE_OBJECT_RELATIONS + 2))

        assert _refusal({TARGET_IDS: selection}).description == OBJECT_RELATION_BULK_TOO_MANY_MESSAGE.format(
            limit=MAX_BULK_DELETE_OBJECT_RELATIONS, count=MAX_BULK_DELETE_OBJECT_RELATIONS + 1,
        )

    def test_the_limit_counts_distinct_ids(self) -> None:
        """Repeating one id past the limit is still one id"""
        assert read_bulk_delete_selection({TARGET_IDS: [9] * (MAX_BULK_DELETE_OBJECT_RELATIONS + 1)}) == [9]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            delete_object_relations                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def _deleting_manager(stored: dict[int, dict[str, Any]], failing_id: int | None = None) -> MagicMock:
    """An ObjectRelationsManager whose find_one_and_delete removes from `stored` and answers what it removed"""
    manager = MagicMock()

    def _find_one_and_delete(criteria: dict[str, Any]) -> dict[str, Any] | None:
        public_id: int = criteria['public_id']

        if public_id == failing_id:
            raise BaseManagerDeleteError('boom')

        return stored.pop(public_id, None)

    manager.find_one_and_delete.side_effect = _find_one_and_delete

    return manager


class TestDeleteObjectRelations:
    """One atomic read-and-delete per id; only what this call removed is collected"""

    def test_every_stored_relation_is_collected_in_order(self) -> None:
        """Each id deleted by its own call"""
        stored = {1: {'public_id': 1}, 2: {'public_id': 2}}
        deleted: list[dict[str, Any]] = []

        delete_object_relations(_deleting_manager(stored), [2, 1], deleted, [])

        assert deleted == [{'public_id': 2}, {'public_id': 1}]
        assert not stored

    def test_an_id_already_gone_is_not_collected(self) -> None:
        """Another writer deleted it, or it never existed"""
        deleted: list[dict[str, Any]] = []

        delete_object_relations(_deleting_manager({3: {'public_id': 3}}), [3, 4], deleted, [])

        assert deleted == [{'public_id': 3}]

    def test_a_failure_leaves_what_was_deleted_before_it(self) -> None:
        """The caller still logs those; the ones after the failure are not attempted"""
        stored = {1: {'public_id': 1}, 2: {'public_id': 2}, 3: {'public_id': 3}}
        deleted: list[dict[str, Any]] = []

        with pytest.raises(BaseManagerDeleteError):
            delete_object_relations(_deleting_manager(stored, failing_id=2), [1, 2, 3], deleted, [])

        assert deleted == [{'public_id': 1}]
        assert sorted(stored) == [2, 3]


# -------------------------------------------------------------------------------------------------------------------- #
#                                         ONE RELATION LINKS ONE PAIR ONCE                                             #
# -------------------------------------------------------------------------------------------------------------------- #
PAIR_RELATION_ID: int = 31
PAIR_PARENT_ID: int = 41
PAIR_CHILD_ID: int = 42
OTHER_INSTANCE_ID: int = 51
OWN_INSTANCE_ID: int = 52


def _pair_write(**extra: Any) -> dict[str, Any]:
    """A validated object relation write"""
    return {'relation_id': PAIR_RELATION_ID, 'relation_parent_id': PAIR_PARENT_ID,
            'relation_child_id': PAIR_CHILD_ID, 'field_values': [], **extra}


def _pair_message() -> str:
    """The 400 naming the pair"""
    return OBJECT_RELATION_PAIR_TAKEN_MESSAGE.format(relation_id=PAIR_RELATION_ID, parent_id=PAIR_PARENT_ID,
                                                     child_id=PAIR_CHILD_ID)


class TestObjectRelationPair:
    """object_relation_pair / object_relation_pair_taken_message"""

    def test_the_pair_is_the_three_keys_of_the_index(self) -> None:
        """Nothing else of the write"""
        assert object_relation_pair(_pair_write(relation_parent_type_id=7)) == {
            'relation_id': PAIR_RELATION_ID, 'relation_parent_id': PAIR_PARENT_ID, 'relation_child_id': PAIR_CHILD_ID,
        }

    def test_the_message_names_relation_and_both_objects(self) -> None:
        """In parent -> child order"""
        assert object_relation_pair_taken_message(_pair_write()) == _pair_message()


class TestAbortIfObjectRelationPairTaken:
    """abort_if_object_relation_pair_taken"""

    def test_a_free_pair_passes(self) -> None:
        """One lookup by the pair"""
        manager = MagicMock()
        manager.get_one_by.return_value = None

        abort_if_object_relation_pair_taken(manager, _pair_write())

        manager.get_one_by.assert_called_once_with(object_relation_pair(_pair_write()))

    def test_a_held_pair_is_refused(self) -> None:
        """400 naming the pair"""
        manager = MagicMock()
        manager.get_one_by.return_value = {'public_id': OTHER_INSTANCE_ID}

        with pytest.raises(HTTPException) as exc_info:
            abort_if_object_relation_pair_taken(manager, _pair_write())

        assert (exc_info.value.code, exc_info.value.description) == (HTTPStatus.BAD_REQUEST, _pair_message())

    def test_an_update_keeps_its_own_pair(self) -> None:
        """The holder is the instance being updated"""
        manager = MagicMock()
        manager.get_one_by.return_value = {'public_id': OWN_INSTANCE_ID}

        abort_if_object_relation_pair_taken(manager, _pair_write(), exclude_id=OWN_INSTANCE_ID)

    def test_an_update_onto_another_instances_pair_is_refused(self) -> None:
        """The holder is someone else"""
        manager = MagicMock()
        manager.get_one_by.return_value = {'public_id': OTHER_INSTANCE_ID}

        with pytest.raises(HTTPException):
            abort_if_object_relation_pair_taken(manager, _pair_write(), exclude_id=OWN_INSTANCE_ID)


class TestAbortIfObjectRelationPairDuplicate:
    """abort_if_object_relation_pair_duplicate - the index refusal of a lost race"""

    def test_a_duplicate_key_in_the_chain_is_the_same_400(self) -> None:
        """Wrapped by the manager"""
        try:
            raise DocumentInsertDuplicateKeyError('dup')
        except DocumentInsertDuplicateKeyError as cause:
            err = ObjectRelationsManagerInsertError(cause)
            err.__cause__ = cause

        with pytest.raises(HTTPException) as exc_info:
            abort_if_object_relation_pair_duplicate(err, _pair_write())

        assert (exc_info.value.code, exc_info.value.description) == (HTTPStatus.BAD_REQUEST, _pair_message())

    def test_any_other_failure_is_left_to_the_caller(self) -> None:
        """No abort - the route answers it as before"""
        cause = DocumentInsertError('down')
        err = ObjectRelationsManagerInsertError(cause)
        err.__cause__ = cause

        assert abort_if_object_relation_pair_duplicate(err, _pair_write()) is None


# --------------------------------------------------- the field identifier rule -------------------------------------- #

def _typed(*fields: tuple[str, str]) -> dict[str, Any]:
    """A relation declaring the given (name, type) fields"""
    return {RelationKey.FIELDS.value: [{'name': name, 'type': field_type} for name, field_type in fields]}


class TestDeclaredFieldTypes:
    """declared_field_types / get_retyped_fields"""

    def test_reads_each_declared_name_with_its_type(self) -> None:
        """Entries that declare nothing are skipped"""
        relation: dict[str, Any] = {RelationKey.FIELDS.value: [
            {'name': 'a', 'type': 'text'}, {'name': 'b'}, {'type': 'text'}, 'junk', {'name': 7, 'type': 'text'},
        ]}

        assert declared_field_types(relation) == {'a': 'text', 'b': None}

    def test_a_kept_name_with_another_type_is_retyped(self) -> None:
        """Sorted; added, removed and unchanged names are not"""
        old: dict[str, Any] = _typed(('b', 'text'), ('a', 'text'), ('same', 'text'), ('gone', 'text'))
        new: dict[str, Any] = _typed(('b', 'date'), ('a', 'number'), ('same', 'text'), ('new', 'date'))

        assert get_retyped_fields(old, new) == ['a', 'b']

    def test_no_fields_no_retyped(self) -> None:
        """A relation without fields"""
        assert get_retyped_fields({}, {}) == []


def _instances(has_instances: bool) -> MagicMock:
    """An ObjectRelationsManager answering whether the relation has instances"""
    manager = MagicMock()
    manager.relation_has_instances.return_value = has_instances

    return manager


class TestRelationFieldIdentifierChangeBlocker:
    """relation_field_identifier_change_blocker - the rename shape while the relation has instances"""

    def test_a_swap_with_instances_is_refused_naming_both_sets(self) -> None:
        """Sorted, comma separated"""
        manager: MagicMock = _instances(True)

        assert relation_field_identifier_change_blocker(
            RELATION_PUBLIC_ID, _relation_declaring('keep', 'b', 'a'), _relation_declaring('keep', 'y', 'x'), manager,
        ) == RELATION_FIELD_IDENTIFIER_IMMUTABLE_MESSAGE.format(removed='a, b', added='x, y')
        manager.relation_has_instances.assert_called_once_with(RELATION_PUBLIC_ID)

    def test_a_swap_without_instances_passes(self) -> None:
        """Nothing to lose"""
        assert relation_field_identifier_change_blocker(
            RELATION_PUBLIC_ID, _relation_declaring('a'), _relation_declaring('b'), _instances(False),
        ) is None

    @pytest.mark.parametrize('old_names, new_names', [
        (('a', 'b'), ('a',)), (('a',), ('a', 'b')), (('a', 'b'), ('b', 'a')),
    ], ids=['removal', 'addition', 'unchanged'])
    def test_no_swap_counts_nothing(self, old_names: tuple[str, ...], new_names: tuple[str, ...]) -> None:
        """No read unless the payload has the shape"""
        manager: MagicMock = _instances(True)

        assert relation_field_identifier_change_blocker(
            RELATION_PUBLIC_ID, _relation_declaring(*old_names), _relation_declaring(*new_names), manager,
        ) is None
        manager.relation_has_instances.assert_not_called()


class TestGuardRelationFieldIdentifierChange:
    """guard_relation_field_identifier_change - the route's 400s"""

    def test_the_swap_is_a_400(self) -> None:
        """The blocker's message"""
        with pytest.raises(HTTPException) as exc_info:
            guard_relation_field_identifier_change(RELATION_PUBLIC_ID, _relation_declaring('a'),
                                                   _relation_declaring('b'), _instances(True))

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.BAD_REQUEST, RELATION_FIELD_IDENTIFIER_IMMUTABLE_MESSAGE.format(removed='a', added='b'),
        )

    def test_an_allowed_update_passes(self) -> None:
        """No abort"""
        guard_relation_field_identifier_change(RELATION_PUBLIC_ID, _relation_declaring('a'),
                                               _relation_declaring('a', 'b'), _instances(True))

    def test_a_failed_count_is_its_own_400(self) -> None:
        """Before anything is written"""
        manager = MagicMock()
        manager.relation_has_instances.side_effect = BaseManagerGetError('down')

        with pytest.raises(HTTPException) as exc_info:
            guard_relation_field_identifier_change(RELATION_PUBLIC_ID, _relation_declaring('a'),
                                                   _relation_declaring('b'), manager)

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.BAD_REQUEST, RELATION_INSTANCE_LOOKUP_FAILED_MESSAGE,
        )

    def test_a_bug_propagates(self) -> None:
        """A programming error is the route's 500"""
        manager = MagicMock()
        manager.relation_has_instances.side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            guard_relation_field_identifier_change(RELATION_PUBLIC_ID, _relation_declaring('a'),
                                                   _relation_declaring('b'), manager)
