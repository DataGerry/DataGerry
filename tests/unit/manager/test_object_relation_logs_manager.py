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
Unit tests for cmdb.manager.object_relation_logs_manager.ObjectRelationLogsManager

Pure tests: no Mongo. ObjectRelationLogsManager is a GenericManager subclass, so the CRUD methods
are thin forwarders to the generic item-level CRUD - those primitives and their error wrapping are
covered by the GenericManager suite. Here each method is invoked unbound against a
``MagicMock(spec=ObjectRelationLogsManager)`` and asserted to delegate correctly; the log-building
logic (``build_object_relation_log``, ``format_object_relation_log_data``, ``get_field_value_changes``,
``check_related_object_changed``) is tested directly.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.object_relation_logs_manager import ObjectRelationLogsManager
from cmdb.models.log_model import LogInteraction
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerBuildError
# -------------------------------------------------------------------------------------------------------------------- #

LOG_PUBLIC_ID: int = 55
NEW_LOG_ID: int = 7
AUTHOR_ID: int = 1
AUTHOR_NAME: str = 'admin'

PARENT_OBJECT_ID: int = 100
CHILD_OBJECT_ID: int = 200
OBJECT_RELATION_ID: int = 300

SAMPLE_LOG: dict[str, Any] = {'public_id': LOG_PUBLIC_ID, 'action': LogInteraction.CREATE}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for an ObjectRelationLogsManager instance."""
    return MagicMock(spec=ObjectRelationLogsManager)


def _mock_user() -> MagicMock:
    """A MagicMock CmdbUser exposing get_public_id / get_display_name."""
    user = MagicMock()
    user.get_public_id.return_value = AUTHOR_ID
    user.get_display_name.return_value = AUTHOR_NAME
    return user


def _object_relation(field_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds the minimal CmdbObjectRelation dict the log builder reads."""
    return {
        'public_id': OBJECT_RELATION_ID,
        'relation_parent_id': PARENT_OBJECT_ID,
        'relation_child_id': CHILD_OBJECT_ID,
        'field_values': field_values if field_values is not None else [],
    }


# --------------------------------------------- insert_object_relation_log ------------------------------------------- #

class TestInsertObjectRelationLog:
    """insert_object_relation_log forwards to the generic insert_item."""

    def test_delegates_to_insert_item(self) -> None:
        """The payload is forwarded to insert_item and its result returned."""
        mgr = _mock_manager()
        mgr.insert_item.return_value = NEW_LOG_ID

        assert ObjectRelationLogsManager.insert_object_relation_log(mgr, SAMPLE_LOG) == NEW_LOG_ID
        mgr.insert_item.assert_called_once_with(SAMPLE_LOG)


# ----------------------------------------------- get_object_relation_log -------------------------------------------- #

class TestGetObjectRelationLog:
    """get_object_relation_log forwards to the generic get_item (raw dict)."""

    def test_delegates_to_get_item_as_dict(self) -> None:
        """get_object_relation_log fetches the raw document via get_item(as_dict=True)."""
        mgr = _mock_manager()
        mgr.get_item.return_value = SAMPLE_LOG

        assert ObjectRelationLogsManager.get_object_relation_log(mgr, LOG_PUBLIC_ID) == SAMPLE_LOG
        mgr.get_item.assert_called_once_with(LOG_PUBLIC_ID, as_dict=True)


# --------------------------------------------------------- iterate -------------------------------------------------- #

class TestIterate:
    """iterate forwards to the generic iterate_items."""

    def test_delegates_to_iterate_items(self) -> None:
        """iterate forwards the builder params to iterate_items and returns its result."""
        mgr = _mock_manager()
        sentinel = MagicMock(name='iteration_result')
        mgr.iterate_items.return_value = sentinel
        builder_params = MagicMock(name='builder_params')

        assert ObjectRelationLogsManager.iterate(mgr, builder_params) is sentinel
        mgr.iterate_items.assert_called_once_with(builder_params)


# ----------------------------------------------- delete_object_relation_log ----------------------------------------- #

class TestDeleteObjectRelationLog:
    """delete_object_relation_log forwards to the generic delete_item."""

    def test_delegates_to_delete_item(self) -> None:
        """delete_object_relation_log forwards the public_id to delete_item and returns its result."""
        mgr = _mock_manager()
        mgr.delete_item.return_value = True

        assert ObjectRelationLogsManager.delete_object_relation_log(mgr, LOG_PUBLIC_ID) is True
        mgr.delete_item.assert_called_once_with(LOG_PUBLIC_ID)


# ----------------------------------------------- build_object_relation_log ------------------------------------------ #

class TestBuildObjectRelationLog:
    """build_object_relation_log formats the log then inserts it."""

    def test_formats_then_inserts(self) -> None:
        """The formatted document from format_object_relation_log_data is passed to insert_object_relation_log."""
        mgr = _mock_manager()
        formatted = {'action': LogInteraction.CREATE}
        mgr.format_object_relation_log_data.return_value = formatted
        user = _mock_user()
        new_relation = _object_relation()

        ObjectRelationLogsManager.build_object_relation_log(mgr, LogInteraction.CREATE, user, None, new_relation)

        mgr.format_object_relation_log_data.assert_called_once_with(
            LogInteraction.CREATE, user, None, new_relation,
        )
        mgr.insert_object_relation_log.assert_called_once_with(formatted)


# --------------------------------------------- format_object_relation_log_data -------------------------------------- #

class TestFormatObjectRelationLogData:
    """format_object_relation_log_data builds the log document per action."""

    def test_create_uses_flat_field_value_snapshot(self) -> None:
        """CREATE stores a flat {name: value} snapshot of the new field values."""
        mgr = _mock_manager()
        new_relation = _object_relation([{'name': 'a', 'value': 1}, {'name': 'b', 'value': 2}])

        log = ObjectRelationLogsManager.format_object_relation_log_data(
            mgr, LogInteraction.CREATE, _mock_user(), None, new_relation,
        )

        assert log['action'] == LogInteraction.CREATE
        assert log['author_id'] == AUTHOR_ID
        assert log['author_name'] == AUTHOR_NAME
        assert log['object_relation_id'] == OBJECT_RELATION_ID
        assert log['object_relation_parent_id'] == PARENT_OBJECT_ID
        assert log['object_relation_child_id'] == CHILD_OBJECT_ID
        assert log['changes'] == {'a': 1, 'b': 2}

    def test_edit_delegates_to_get_field_value_changes(self) -> None:
        """EDIT stores the structured diff returned by get_field_value_changes."""
        mgr = _mock_manager()
        diff = {'modified': {}, 'added': {}, 'deleted': {}}
        mgr.get_field_value_changes.return_value = diff
        old_relation = _object_relation([{'name': 'a', 'value': 1}])
        new_relation = _object_relation([{'name': 'a', 'value': 2}])

        log = ObjectRelationLogsManager.format_object_relation_log_data(
            mgr, LogInteraction.EDIT, _mock_user(), old_relation, new_relation,
        )

        assert log['changes'] is diff
        mgr.get_field_value_changes.assert_called_once_with(
            old_relation['field_values'], new_relation['field_values'],
        )

    def test_delete_has_empty_changes(self) -> None:
        """DELETE leaves changes empty (the relation is gone)."""
        mgr = _mock_manager()
        old_relation = _object_relation([{'name': 'a', 'value': 1}])

        log = ObjectRelationLogsManager.format_object_relation_log_data(
            mgr, LogInteraction.DELETE, _mock_user(), old_relation, None,
        )

        assert log['changes'] == {}
        assert log['object_relation_id'] == OBJECT_RELATION_ID

    def test_raises_build_error_when_no_relation_provided(self) -> None:
        """Neither old nor new relation provided raises ObjectRelationLogsManagerBuildError."""
        with pytest.raises(ObjectRelationLogsManagerBuildError):
            ObjectRelationLogsManager.format_object_relation_log_data(
                _mock_manager(), LogInteraction.DELETE, _mock_user(), None, None,
            )


# --------------------------------------------------- get_field_value_changes ---------------------------------------- #

class TestGetFieldValueChanges:
    """get_field_value_changes computes the modified/added/deleted diff (pure)."""

    def test_detects_modified_added_deleted(self) -> None:
        """A value change, a new field, and a removed field are each classified correctly."""
        old_fields = [{'name': 'status', 'value': 'active'}, {'name': 'owner', 'value': 'Alice'}]
        new_fields = [{'name': 'status', 'value': 'inactive'}, {'name': 'assigned_to', 'value': 'Bob'}]

        changes = ObjectRelationLogsManager.get_field_value_changes(_mock_manager(), old_fields, new_fields)

        assert changes['modified'] == {'status': {'before': 'active', 'after': 'inactive'}}
        assert changes['added'] == {'assigned_to': 'Bob'}
        assert changes['deleted'] == {'owner': 'Alice'}

    def test_no_changes_yields_empty_diff(self) -> None:
        """Identical field values produce empty modified/added/deleted dicts."""
        fields = [{'name': 'a', 'value': 1}]

        changes = ObjectRelationLogsManager.get_field_value_changes(_mock_manager(), fields, list(fields))

        assert changes == {'modified': {}, 'added': {}, 'deleted': {}}


# --------------------------------------------------- check_related_object_changed ----------------------------------- #

class TestCheckRelatedObjectChanged:
    """check_related_object_changed flags a changed parent or child object id."""

    def test_returns_false_when_endpoints_unchanged(self) -> None:
        """Same parent and child ids return False."""
        relation = {'relation_parent_id': PARENT_OBJECT_ID, 'relation_child_id': CHILD_OBJECT_ID}

        assert ObjectRelationLogsManager.check_related_object_changed(_mock_manager(), relation, dict(relation)) \
            is False

    def test_returns_true_when_parent_changed(self) -> None:
        """A changed parent id returns True."""
        old = {'relation_parent_id': PARENT_OBJECT_ID, 'relation_child_id': CHILD_OBJECT_ID}
        new = {'relation_parent_id': 999, 'relation_child_id': CHILD_OBJECT_ID}

        assert ObjectRelationLogsManager.check_related_object_changed(_mock_manager(), old, new) is True

    def test_returns_true_when_child_changed(self) -> None:
        """A changed child id returns True."""
        old = {'relation_parent_id': PARENT_OBJECT_ID, 'relation_child_id': CHILD_OBJECT_ID}
        new = {'relation_parent_id': PARENT_OBJECT_ID, 'relation_child_id': 999}

        assert ObjectRelationLogsManager.check_related_object_changed(_mock_manager(), old, new) is True
