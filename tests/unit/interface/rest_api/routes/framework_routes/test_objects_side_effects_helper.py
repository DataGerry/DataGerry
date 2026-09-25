# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper

Pure tests, no Mongo: every collaborator is a MagicMock resolved through a patched ManagerProvider.

The property these tests exist for is that **each side effect is best-effort**: a webhook that cannot
be sent, a log that cannot be written or a config-item sync that fails must never propagate, because
the object they describe has already been stored. Most tests here therefore assert that something does
NOT raise, and that the next side effect still ran.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import OBJECT_LOG_LOST_MARKER
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    build_object_log_data,
    build_object_write_emitter,
    log_object_change,
    report_lost_object_log,
    write_object_log,
    RELATION_DELETE_LOG_PROJECTION,
    build_type_object_counts,
    emit_object_state_change_events,
    emit_object_update_events,
    handle_create_object_log,
    handle_delete_invalid_object_relations,
    handle_delete_object_location,
    handle_notify_webhooks,
    handle_sync_config_item_count,
    render_single_object,
)
from cmdb.models.object_model import CmdbObject
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.object_edit import ObjectWrite
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper'


def _make_object(fields: list[dict[str, Any]], special_type: Any = None, public_id: int = 1) -> CmdbObject:
    """Builds a minimal valid CmdbObject for the helper unit tests."""
    return CmdbObject(
        public_id=public_id,
        type_id=1,
        version='1.0.0',
        creation_time=datetime.now(timezone.utc),
        author_id=1,
        active=True,
        fields=fields,
        special_type=special_type,
    )


def _rendered(object_id: int = 5, version: str = '1.0.1') -> MagicMock:
    """A RenderResult stand-in carrying the object_information a log entry reads."""
    rendered = MagicMock(spec=RenderResult)
    rendered.object_information = {'object_id': object_id, 'version': version}

    return rendered


class TestEmitObjectUpdateEvents:
    """emit_object_update_events fires the webhook and writes the edit log, each best-effort."""

    @pytest.fixture(autouse=True)
    def _encodable_render(self):
        """The render stand-in is a mock; its JSON encoding is not what these tests are about."""
        with patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            yield

    def test_emits_webhook_and_log(self) -> None:
        """Both the update webhook and the edit log are produced on the happy path."""
        logs_manager = MagicMock()
        before = _make_object([{'name': 'a', 'value': 1}])
        after = _make_object([{'name': 'a', 'value': 2}])
        updated = _make_object([{'name': 'a', 'value': 2}])

        with patch(f'{HELPER_PATH}.send_webhook_event') as webhook, \
             patch(f'{HELPER_PATH}.render_single_object', return_value=_rendered()):
            emit_object_update_events(MagicMock(), logs_manager, before, after, updated, {'new': []}, "note")

        webhook.assert_called_once()
        logs_manager.insert_log.assert_called_once()

    def test_the_edit_log_stores_the_rendered_object(self) -> None:
        """
        render_state is the RENDERED updated object, like every other log action

        The log view draws render_state with the object renderer; the stored document carries no type,
        section or summary information, so an edit entry built from it rendered empty.
        """
        logs_manager = MagicMock()
        after = _make_object([{'name': 'a', 'value': 2}])
        rendered = _rendered()

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=rendered) as render, \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{"rendered": true}') as dumps:
            emit_object_update_events(MagicMock(), logs_manager, after, after, after, {'new': []}, 'note')

        assert render.call_args.args[0] is after
        assert dumps.call_args.args[0] is rendered
        kwargs = logs_manager.insert_log.call_args.kwargs
        assert kwargs['render_state'] == b'{"rendered": true}'
        assert kwargs['changes'] == {'new': []}
        assert kwargs['comment'] == 'note'
        assert kwargs['action'] == LogAction.EDIT

    def test_the_bumped_version_is_recorded(self) -> None:
        """The candidate's version, not whatever the render shows"""
        logs_manager = MagicMock()
        obj = _make_object([{'name': 'a', 'value': 1}])
        updated = MagicMock()
        updated.get_version.return_value = '2.0.0'

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=_rendered(version='1.0.0')):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, updated, {}, '')

        assert logs_manager.insert_log.call_args.kwargs['version'] == '2.0.0'

    def test_webhook_failure_does_not_block_log(self) -> None:
        """A webhook error is swallowed and the edit log is still written."""
        logs_manager = MagicMock()
        obj = _make_object([{'name': 'a', 'value': 1}])

        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError("boom")), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=_rendered()):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, obj, {'new': []}, "")

        logs_manager.insert_log.assert_called_once()

    def test_log_failure_is_swallowed(self) -> None:
        """A logging error never propagates out of the helper."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError("boom")
        obj = _make_object([{'name': 'a', 'value': 1}])

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=_rendered()):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, obj, {'new': []}, "")  # must not raise

    def test_an_unrenderable_object_is_reported_and_writes_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """No entry with a raw document is written in its place - the loss is reported instead"""
        logs_manager = MagicMock()
        obj = _make_object([{'name': 'a', 'value': 1}])

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=None):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, obj, {}, '')

        logs_manager.insert_log.assert_not_called()
        assert OBJECT_LOG_LOST_MARKER in caplog.text


class TestLostLogsAreObservable:
    """Every lost entry is logged under one marker, with what was lost and why."""

    def test_the_report_carries_the_marker_action_and_object(self, caplog: pytest.LogCaptureFixture) -> None:
        """One search for the marker finds every lost entry"""
        report_lost_object_log(LogAction.EDIT, 42, 'because')

        assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id=42: because' in caplog.text

    def test_the_report_attaches_the_traceback_when_asked(self, caplog: pytest.LogCaptureFixture) -> None:
        """The exception being handled is not reduced to its message"""
        try:
            raise RuntimeError('disk full')
        except RuntimeError:
            report_lost_object_log(LogAction.CREATE, 1, 'the log entry could not be written', with_traceback=True)

        assert caplog.records[-1].exc_info is not None
        assert 'disk full' in caplog.text

    def test_the_marker_is_a_fixed_text(self) -> None:
        """Operators alert on it, so it may not drift"""
        assert OBJECT_LOG_LOST_MARKER == 'OBJECT_LOG_LOST'


class TestWriteObjectLog:
    """write_object_log - the one place an entry is inserted."""

    def test_a_written_entry_answers_true(self) -> None:
        """The entry goes to insert_log as a CmdbObjectLog"""
        logs_manager = MagicMock()

        assert write_object_log(logs_manager, LogAction.EDIT, {'object_id': 3}) is True
        logs_manager.insert_log.assert_called_once_with(action=LogAction.EDIT, log_type='CmdbObjectLog', object_id=3)

    def test_a_failing_insert_answers_false_and_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """Never raised - the object write it follows is already done"""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError('logs collection down')

        assert write_object_log(logs_manager, LogAction.DELETE, {'object_id': 3}) is False
        assert f'{OBJECT_LOG_LOST_MARKER} action=DELETE object_id=3' in caplog.text
        assert caplog.records[-1].exc_info is not None


class TestBuildObjectLogData:
    """The entry every object write path stores."""

    def test_builds_the_entry_from_the_render(self) -> None:
        """The user, the comment, the version and the JSON-encoded render"""
        user = MagicMock()
        user.get_public_id.return_value = 1
        user.get_display_name.return_value = 'admin'

        with patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            entry = build_object_log_data(user, 5, '1.0.1', 'note', _rendered(), {'old': 1, 'new': 2})

        assert entry == {
            'object_id': 5, 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin', 'comment': 'note',
            'render_state': b'{}', 'changes': {'old': 1, 'new': 2},
        }

    def test_an_action_without_changes_stores_no_changes_key(self) -> None:
        """Create, delete and import record no diff"""
        with patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            entry = build_object_log_data(MagicMock(), 5, '1.0.1', 'note', _rendered())

        assert 'changes' not in entry


class TestLogObjectChange:
    """log_object_change - render, build, write, and never raise."""

    def test_the_version_defaults_to_the_rendered_one(self) -> None:
        """Create and delete record the version the render shows"""
        logs_manager = MagicMock()
        target = MagicMock()
        target.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.render_single_object', return_value=_rendered(version='3.1.0')), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            assert log_object_change(MagicMock(), logs_manager, LogAction.CREATE, target, 'c') is True

        assert logs_manager.insert_log.call_args.kwargs['version'] == '3.1.0'

    def test_a_failing_render_is_reported_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        """An exception while rendering costs the entry, never the write"""
        target = MagicMock()
        target.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.render_single_object', side_effect=RuntimeError('render broke')):
            assert log_object_change(MagicMock(), MagicMock(), LogAction.EDIT, target, 'c') is False

        assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id=5: the log entry could not be built' in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                              sync_select_field_options                                               #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleDeleteObjectLocation:
    """handle_delete_object_location deletes the object's location, promoting its direct children."""

    def test_deletes_location_via_reparenting_helper(self) -> None:
        """The object's location is handed to the re-parenting delete helper."""
        location = {'public_id': 50, 'parent': 1}
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = location

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5)

        reparent.assert_called_once()
        assert reparent.call_args.args[0] == location

    def test_no_location_is_noop(self) -> None:
        """When the object has no location nothing is deleted."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = None

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5)

        reparent.assert_not_called()

    def test_passed_in_managers_skip_the_provider_lookup(self) -> None:
        """When both managers are supplied (e.g. a bulk loop) no ManagerProvider lookup happens."""
        location = {'public_id': 50, 'parent': 1}
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = location
        objects_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager') as get_manager, \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5, locations_manager, objects_manager)

        get_manager.assert_not_called()
        reparent.assert_called_once_with(location, locations_manager, objects_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                apply_object_update                                                   #
# -------------------------------------------------------------------------------------------------------------------- #


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

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        assert type_counts == [{'name': 'Server', 'count': 30}, {'name': 'Client', 'count': 12}]
        assert total == 42

    def test_no_objects_returns_empty_without_type_lookup(self) -> None:
        """With no objects the helper returns [] and never queries the type lookup."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({}, 0)
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
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

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        # the skipped type still counts toward the total the portal is told about
        assert type_counts == [{'name': 'Server', 'count': 30}]
        assert total == 35


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_sync_config_item_count                                              #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleSyncConfigItemCount:
    """handle_sync_config_item_count forwards the count plus the per-type breakdown to the portal."""

    def test_passes_count_and_type_breakdown_to_manager(self) -> None:
        """The built type-count list is passed straight into DgServicePortalManager.sync_config_items."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{'name': 'Server', 'count': 30}]

        with patch(f'{HELPER_PATH}.build_type_object_counts', return_value=(type_counts, 30)), \
             patch(f'{HELPER_PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user, 42)

        # an explicitly supplied count wins over the aggregation's total
        manager_instance.sync_config_items.assert_called_once_with(request_user, 42, type_counts)

    def test_derives_the_total_from_the_breakdown_when_no_count_is_given(self) -> None:
        """Omitting the count takes the total from the same aggregation - no extra full-collection count."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{'name': 'Server', 'count': 30}]

        with patch(f'{HELPER_PATH}.build_type_object_counts', return_value=(type_counts, 31)), \
             patch(f'{HELPER_PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user)

        manager_instance.sync_config_items.assert_called_once_with(request_user, 31, type_counts)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_object_patch_payload                                              #
# -------------------------------------------------------------------------------------------------------------------- #


class TestEmitObjectStateChangeEvents:
    """emit_object_state_change_events emits the UPDATE webhook and writes the ACTIVE_CHANGE log."""

    def _objects(self) -> tuple[CmdbObject, CmdbObject]:
        """Builds a before/after CmdbObject pair for the state-change events."""
        before = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=5)
        after = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=5)
        return before, after

    def test_emits_webhook_and_writes_log(self) -> None:
        """The webhook fires and an ACTIVE_CHANGE log is inserted with the old/new change dict."""
        before, after = self._objects()
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event') as webhook:
            emit_object_state_change_events(MagicMock(), logs_manager, before, after, {'rendered': True}, True)

        webhook.assert_called_once()
        logs_manager.insert_log.assert_called_once()
        assert logs_manager.insert_log.call_args.kwargs['changes'] == {'old': False, 'new': True}

    def test_webhook_failure_does_not_block_log(self) -> None:
        """A webhook exception is swallowed; the log is still written."""
        before, after = self._objects()
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError('boom')):
            emit_object_state_change_events(MagicMock(), logs_manager, before, after, {'rendered': True}, False)

        logs_manager.insert_log.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            realign_objects_to_type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #


class TestRenderSingleObject:
    """render_single_object collapses CmdbMultiRender's union down to RenderResult | None."""

    def test_returns_the_rendered_result(self) -> None:
        """A real RenderResult is handed straight back."""
        rendered = MagicMock(spec=RenderResult)

        with patch(f'{HELPER_PATH}.CmdbMultiRender') as multi_render:
            multi_render.return_value.result.return_value = rendered

            assert render_single_object(MagicMock(), MagicMock()) is rendered

    @pytest.mark.parametrize('produced', [None, [], ['not-a-render-result']])
    def test_anything_that_is_not_a_render_result_becomes_none(self, produced: Any) -> None:
        """None (type gone) and the list shape both collapse to None instead of leaking out."""
        with patch(f'{HELPER_PATH}.CmdbMultiRender') as multi_render:
            multi_render.return_value.result.return_value = produced

            assert render_single_object(MagicMock(), MagicMock()) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              handle_notify_webhooks                                                  #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleNotifyWebhooks:
    """handle_notify_webhooks emits the event and never lets a webhook failure escape."""

    @pytest.mark.parametrize('event_type, expected_kwarg', [
        (WebhookEventType.CREATE, 'object_after'),
        (WebhookEventType.DELETE, 'object_before'),
    ])
    def test_sends_the_event_under_the_right_keyword(self, event_type: Any, expected_kwarg: str) -> None:
        """A create reports the object as 'after', a delete as 'before'."""
        target = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event') as send, \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={'public_id': 5}):
            handle_notify_webhooks(MagicMock(), target, event_type)

        assert expected_kwarg in send.call_args.kwargs

    def test_a_failing_webhook_is_swallowed(self) -> None:
        """A webhook problem must never roll back or fail the surrounding object operation."""
        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError('webhook down')), \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={}):
            handle_notify_webhooks(MagicMock(), MagicMock(), WebhookEventType.CREATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             handle_create_object_log                                                 #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleCreateObjectLog:
    """handle_create_object_log writes the audit entry, best-effort."""

    def test_writes_the_log_entry(self) -> None:
        """The rendered object's id and version land on the persisted log document."""
        logs_manager = MagicMock()
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        target = MagicMock()
        target.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), target, LogAction.CREATE)

        assert logs_manager.insert_log.call_args.kwargs['object_id'] == 5
        assert logs_manager.insert_log.call_args.kwargs['version'] == '1.0.1'
        assert logs_manager.insert_log.call_args.kwargs['comment'] == 'Object created'

    def test_a_delete_is_labelled_as_one(self) -> None:
        """The DELETE action gets its own comment."""
        logs_manager = MagicMock()
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.DELETE)

        assert logs_manager.insert_log.call_args.kwargs['comment'] == 'Object was deleted'

    def test_an_unrenderable_object_writes_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """A render that yields nothing is reported under the marker and skipped."""
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.render_single_object', return_value=None), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.CREATE)

        logs_manager.insert_log.assert_not_called()
        assert OBJECT_LOG_LOST_MARKER in caplog.text
        assert 'the object could not be rendered' in caplog.text

    def test_an_unresolvable_logs_manager_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """Even the manager lookup is inside the best-effort boundary"""
        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=RuntimeError('no db')):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.DELETE)

        assert f'{OBJECT_LOG_LOST_MARKER} action=DELETE' in caplog.text

    def test_a_failing_log_write_is_swallowed(self, caplog: pytest.LogCaptureFixture) -> None:
        """A logging problem must never fail the surrounding object operation - it is reported instead."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError('logs collection down')
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.CREATE)

        assert OBJECT_LOG_LOST_MARKER in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                       handle_delete_invalid_object_relations                                         #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleDeleteInvalidObjectRelations:
    """The relation half of the object-delete cascade: bulk delete plus one log per relation."""

    @staticmethod
    def _managers(relations: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
        """Builds the relation + relation-log managers with the given relations found."""
        relations_manager = MagicMock()
        relations_manager.find.return_value = relations
        relations_manager.get_related_relations_query.return_value = {'$or': []}
        logs_manager = MagicMock()

        return relations_manager, logs_manager

    def test_no_relations_writes_nothing(self) -> None:
        """An object with no relations short-circuits before the delete and the log work."""
        relations_manager, logs_manager = self._managers([])

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_not_called()
        logs_manager.insert_many.assert_not_called()

    def test_reads_back_only_the_keys_the_log_needs(self) -> None:
        """The relations are read with a projection - the full documents are never loaded."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}])
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}]
        logs_manager.reserve_public_ids.return_value = [10]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        assert relations_manager.find.call_args.kwargs['projection'] == RELATION_DELETE_LOG_PROJECTION

    def test_deletes_and_logs_every_affected_relation(self) -> None:
        """One bulk delete, one reserved id per log, then a single insert_many."""
        relations = [{'public_id': 1}, {'public_id': 2}]
        relations_manager, logs_manager = self._managers(relations)
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}, {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [10, 11]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_called_once_with({'$or': []})
        logs_manager.reserve_public_ids.assert_called_once_with(2)
        logs_manager.insert_many.assert_called_once_with(
            [{'a': 1, 'public_id': 10}, {'b': 2, 'public_id': 11}], skip_public=True,
        )

    def test_a_failing_log_prep_skips_only_that_relation(self) -> None:
        """One unformattable relation must not cost the others their log entry."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}, {'public_id': 2}])
        logs_manager.format_object_relation_log_data.side_effect = [RuntimeError('bad relation'), {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [11]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        logs_manager.insert_many.assert_called_once_with([{'b': 2, 'public_id': 11}], skip_public=True)

    def test_every_log_prep_failing_writes_no_logs(self) -> None:
        """The relations are still deleted, but there is nothing to insert."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}])
        logs_manager.format_object_relation_log_data.side_effect = RuntimeError('bad relation')

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_called_once()
        logs_manager.reserve_public_ids.assert_not_called()
        logs_manager.insert_many.assert_not_called()

    def test_a_short_id_reservation_fails_loudly(self) -> None:
        """
        insert_many(skip_public=True) needs a public_id on EVERY document

        Without strict pairing the surplus logs would be inserted with the key missing, which the
        unique index answers with a duplicate-key error on the second null - so the mismatch has to
        surface here instead.
        """
        relations_manager, logs_manager = self._managers([{'public_id': 1}, {'public_id': 2}])
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}, {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [10]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            with pytest.raises(ValueError):
                handle_delete_invalid_object_relations(MagicMock(), 5)

        logs_manager.insert_many.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_config_item_limit                                                 #
# -------------------------------------------------------------------------------------------------------------------- #


class TestHandleDeleteObjectLocationErrorArms:
    """The two ways the location cleanup can fail, which it maps rather than lets escape."""

    def test_a_failing_location_delete_becomes_500(self) -> None:
        """An unexpected locations failure is mapped onto a 500 instead of escaping raw."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.side_effect = RuntimeError('locations down')

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            with pytest.raises(HTTPException) as exc_info:
                handle_delete_object_location(MagicMock(), 5)

        assert exc_info.value.code == 500

    def test_an_http_error_from_the_location_delete_propagates(self) -> None:
        """A 400 raised while re-parenting reaches the client instead of being masked as a 500."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = {'public_id': 50}

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting', side_effect=BadRequest('nope')):
            with pytest.raises(HTTPException) as exc_info:
                handle_delete_object_location(MagicMock(), 5)

        assert exc_info.value.code == 400


class TestEmitObjectStateChangeEventsErrorArm:
    """The state-change events are best-effort like every other side effect."""

    def test_a_failing_state_change_log_is_swallowed(self) -> None:
        """A logging problem must not fail an activate / deactivate that already happened."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError('logs collection down')
        before = MagicMock()
        before.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={}), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            emit_object_state_change_events(MagicMock(), logs_manager, before, MagicMock(), {}, True)

        logs_manager.insert_log.assert_called_once()

    def test_an_entry_that_cannot_be_built_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unencodable render costs the entry and is reported under the marker - nothing is written"""
        logs_manager = MagicMock()
        before = MagicMock()
        before.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={}), \
             patch(f'{HELPER_PATH}.json.dumps', side_effect=TypeError('not serialisable')):
            emit_object_state_change_events(MagicMock(), logs_manager, before, MagicMock(), {}, False)

        logs_manager.insert_log.assert_not_called()
        assert f'{OBJECT_LOG_LOST_MARKER} action=ACTIVE_CHANGE object_id=5: the log entry could not be built' \
            in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_object_write_emitter                                               #
# -------------------------------------------------------------------------------------------------------------------- #
EMITTER_COMMENT: str = 'Subnet unassigned from its supernet'


def _object_write() -> ObjectWrite:
    """A stored edit: version 1.0.0 before, 1.0.1 after."""
    before = _make_object([{'name': 'ref', 'value': 7}])
    after = _make_object([{'name': 'ref', 'value': None}])
    after.version = '1.0.1'

    return ObjectWrite(before, after, {'old': [{'name': 'ref', 'value': 7}], 'new': [{'name': 'ref', 'value': None}]})


class TestBuildObjectWriteEmitter:
    """The callback a framework write hands its stored edits to."""

    def test_building_the_emitter_resolves_no_manager(self) -> None:
        """A request refused before anything is written must not pay for a LogsManager."""
        with patch(f'{HELPER_PATH}.ManagerProvider') as provider:
            build_object_write_emitter(MagicMock(), EMITTER_COMMENT)

        provider.get_manager.assert_not_called()

    def test_each_write_emits_the_update_events_with_the_comment(self) -> None:
        """before / after / diff reach the webhook + edit log exactly as the REST update sends them."""
        request_user = MagicMock()
        write = _object_write()

        with patch(f'{HELPER_PATH}.ManagerProvider') as provider, \
             patch(f'{HELPER_PATH}.emit_object_update_events') as emit:
            build_object_write_emitter(request_user, EMITTER_COMMENT)(write)

        emit.assert_called_once_with(
            request_user, provider.get_manager.return_value, write.before, write.after, write.after, write.changes,
            EMITTER_COMMENT,
        )

    def test_the_logs_manager_is_resolved_once_for_every_write(self) -> None:
        """A batch of N writes resolves one LogsManager, not N."""
        with patch(f'{HELPER_PATH}.ManagerProvider') as provider, \
             patch(f'{HELPER_PATH}.emit_object_update_events') as emit:
            emitter = build_object_write_emitter(MagicMock(), EMITTER_COMMENT)
            emitter(_object_write())
            emitter(_object_write())

        provider.get_manager.assert_called_once()
        assert emit.call_count == 2

    def test_the_log_records_the_version_the_write_stored(self) -> None:
        """Unpatched below the helper: the entry carries the AFTER version and the edit comment."""
        logs_manager = MagicMock()
        rendered = _rendered(version='1.0.0')

        with patch(f'{HELPER_PATH}.ManagerProvider') as provider, \
             patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            provider.get_manager.return_value = logs_manager
            build_object_write_emitter(MagicMock(), EMITTER_COMMENT)(_object_write())

        kwargs = logs_manager.insert_log.call_args.kwargs
        assert kwargs['action'] == LogAction.EDIT
        assert kwargs['version'] == '1.0.1'
        assert kwargs['comment'] == EMITTER_COMMENT
