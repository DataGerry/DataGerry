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
Unit tests for cmdb.framework.person_sync.sync_engine

What the engine does on a real database is the integration test's. Pinned here: while a sync is off nothing is read
or written; a user without a chosen target is refused; a merged result keeps an object's first state as its before;
the events go out only with callbacks, created persons through ``on_create`` and edits through the hand-over
"""
# pylint: disable=protected-access
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.user_model import CmdbUser
from cmdb.framework.object_edit import PlannedEdit
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.sync_engine import (
    SyncContext,
    SyncEvents,
    SyncResult,
    _clear_sync_pending,
    _sync_groups,
    emit_sync_events,
    insert_linked_object,
    left_synced_members,
    record_left_members,
    sync_user,
    sync_user_deleted,
    sync_user_group,
    write_edit,
)
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

ENGINE_PATH: str = 'cmdb.framework.person_sync.sync_engine'
USER: CmdbUser = CmdbUser(public_id=7, user_name='ann', active=True, group_ids=[2])
PERSON_ID: int = 501


def _context(settings: PersonSyncSettings) -> SyncContext:
    """A context of mocked managers"""
    return SyncContext(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings,
                       CmdbUser(public_id=1, user_name='admin', active=True))


class TestWhileOff:
    """Nothing is read or written."""

    def test_sync_user(self) -> None:
        """The user sync is off"""
        context = _context(PersonSyncSettings())

        assert sync_user(context, WriteLedger(), USER) == SyncResult()
        context.objects_manager.find.assert_not_called()

    def test_sync_user_deleted_still_unlinks(self) -> None:
        """The exception: with the user gone there is nothing to mirror - its person is looked up and unlinked"""
        context = _context(PersonSyncSettings())
        context.objects_manager.find.return_value = []

        assert sync_user_deleted(context, WriteLedger(), USER.public_id) == SyncResult()
        context.objects_manager.find.assert_called_once()

    @pytest.mark.parametrize('settings', [
        PersonSyncSettings(users=UserSyncSettings(active=True)),
        PersonSyncSettings(groups=GroupSyncSettings(active=True)),
    ], ids=['group-sync-off', 'user-sync-off'])
    def test_sync_user_group(self, settings: PersonSyncSettings) -> None:
        """Both syncs must be on"""
        context = _context(settings)

        assert sync_user_group(context, WriteLedger(), SimpleNamespace(public_id=2)) == SyncResult()
        context.objects_manager.find.assert_not_called()


def test_a_user_without_a_chosen_target_is_refused() -> None:
    """Switched on, no default - the settings rules keep this from being stored; the engine refuses it anyway"""
    context = _context(PersonSyncSettings(users=UserSyncSettings(active=True)))
    context.objects_manager.find.return_value = []

    with pytest.raises(PersonSyncTargetError):
        sync_user(context, WriteLedger(), USER)

    context.objects_manager.insert.assert_not_called()


def test_a_merged_result_keeps_the_first_before() -> None:
    """An object edited twice: the first state, the last version and diff"""
    first_before, second_before = MagicMock(), MagicMock()
    result = SyncResult(created=[1], edits={PERSON_ID: PlannedEdit(first_before, '1.0.1', {'old': ['a']})})

    result.merge(SyncResult(created=[2], edits={PERSON_ID: PlannedEdit(second_before, '1.0.2', {'old': ['b']})}))

    assert result.created == [1, 2]
    assert result.edits[PERSON_ID] == PlannedEdit(first_before, '1.0.2', {'old': ['b']})


@pytest.mark.parametrize(('first', 'second'), [(True, False), (False, True), (True, True)],
                         ids=['first', 'second', 'both'])
def test_merge_keeps_a_moved_config_item_count(first: bool, second: bool) -> None:
    """Either call having linked or unlinked a stored object moved the count"""
    result = SyncResult(config_items_changed=first)

    result.merge(SyncResult(config_items_changed=second))

    assert result.config_items_changed is True


def test_merge_of_two_unmoved_counts_stays_unmoved() -> None:
    """Nothing linked or unlinked on either side"""
    result = SyncResult()

    result.merge(SyncResult())

    assert result.config_items_changed is False


class TestEmitSyncEvents:
    """What goes to the route layer."""

    def test_no_callbacks_emit_nothing(self) -> None:
        """A caller that wants no logs"""
        objects_manager = MagicMock()

        emit_sync_events(objects_manager, SyncResult(created=[PERSON_ID]), None)

        objects_manager.find_objects.assert_not_called()

    def test_created_persons_and_edits_are_handed_over(self) -> None:
        """Created read back in one query; edits through the shared hand-over"""
        objects_manager = MagicMock()
        stored: dict[str, Any] = {'public_id': PERSON_ID, 'type_id': 3, 'author_id': 1, 'fields': []}
        objects_manager.find_objects.return_value = [stored]
        events = SyncEvents(on_create=MagicMock(), on_edit=MagicMock(), on_config_items_changed=MagicMock())
        result = SyncResult(created=[PERSON_ID], edits={9: MagicMock()})

        with patch(f'{ENGINE_PATH}.hand_over_object_writes') as hand_over:
            emit_sync_events(objects_manager, result, events)

        assert events.on_create.call_args.args[0].public_id == PERSON_ID
        hand_over.assert_called_once_with(objects_manager, result.edits, events.on_edit)
        events.on_config_items_changed.assert_not_called()

    def test_a_moved_config_item_count_is_reported_once(self) -> None:
        """After the logs, one report however many links moved"""
        events = SyncEvents(on_create=MagicMock(), on_edit=MagicMock(), on_config_items_changed=MagicMock())

        with patch(f'{ENGINE_PATH}.hand_over_object_writes'):
            emit_sync_events(MagicMock(), SyncResult(config_items_changed=True), events)

        events.on_config_items_changed.assert_called_once_with()

    def test_a_failed_read_back_loses_only_the_create_events(self) -> None:
        """Best-effort: logged, never raised; the edits still go out"""
        objects_manager = MagicMock()
        objects_manager.find_objects.side_effect = RuntimeError('read failed')
        events = SyncEvents(on_create=MagicMock(), on_edit=MagicMock(), on_config_items_changed=MagicMock())

        with patch(f'{ENGINE_PATH}.hand_over_object_writes') as hand_over:
            emit_sync_events(objects_manager, SyncResult(created=[PERSON_ID]), events)

        events.on_create.assert_not_called()
        hand_over.assert_called_once()


class TestClearSyncPending:
    """A sync that succeeded settles its users' marks, recorded for the undo - one read and one write for all."""

    @staticmethod
    def _marked(public_id: int) -> CmdbUser:
        """A user carrying the mark"""
        return CmdbUser(public_id=public_id, user_name=f'user{public_id}', active=True, sync_pending=True)

    def test_unmarked_users_read_nothing(self) -> None:
        """The common case costs no read"""
        context = _context(PersonSyncSettings())

        _clear_sync_pending(context, WriteLedger(), [USER])

        context.users_manager.find.assert_not_called()
        context.users_manager.update_many_raw.assert_not_called()

    def test_the_marked_users_lose_the_mark_and_the_ledger_keeps_each(self) -> None:
        """One read of the marked ones, one unset for those still stored with it"""
        context = _context(PersonSyncSettings())
        stored: list[dict[str, Any]] = [{'public_id': 8, 'sync_pending': True}, {'public_id': 9, 'sync_pending': True}]
        context.users_manager.find.return_value = stored
        ledger = MagicMock()

        _clear_sync_pending(context, ledger, [self._marked(9), USER, self._marked(8)])

        assert context.users_manager.find.call_args.kwargs['criteria'] == {
            'public_id': {'$in': [8, 9]}, 'sync_pending': {'$exists': True}}
        context.users_manager.update_many_raw.assert_called_once_with({'public_id': {'$in': [8, 9]}},
                                                                      {'$unset': {'sync_pending': ''}})
        assert [call.args[1:] for call in ledger.updated.call_args_list] == [(8, stored[0]), (9, stored[1])]

    def test_marks_already_gone_write_nothing(self) -> None:
        """Another sync settled them in between"""
        context = _context(PersonSyncSettings())
        context.users_manager.find.return_value = []

        _clear_sync_pending(context, WriteLedger(), [self._marked(8)])

        context.users_manager.update_many_raw.assert_not_called()

class TestTheLedgerOrder:
    """Every write is recorded before it runs, so an update applied but unanswered is undone too."""

    def test_an_edit_is_recorded_before_the_update(self) -> None:
        """The stored document, then the write"""
        context = _context(PersonSyncSettings())
        calls: list[str] = []
        ledger = MagicMock()
        ledger.updated.side_effect = lambda *_args: calls.append('recorded')
        context.objects_manager.update.side_effect = lambda *_args: calls.append('written')
        stored: dict[str, Any] = {'public_id': PERSON_ID, 'type_id': 1, 'author_id': 1, 'active': True,
                                  'version': '1.0.0', 'fields': []}

        write_edit(context, ledger, stored, {**stored, 'active': False})

        assert calls == ['recorded', 'written']

    def test_the_marked_users_are_recorded_before_the_unset(self) -> None:
        """The same order for the sync_pending marks"""
        context = _context(PersonSyncSettings())
        calls: list[str] = []
        ledger = MagicMock()
        ledger.updated.side_effect = lambda *_args: calls.append('recorded')
        context.users_manager.update_many_raw.side_effect = lambda *_args: calls.append('written')
        context.users_manager.find.return_value = [{'public_id': USER.public_id, 'sync_pending': True}]

        _clear_sync_pending(context, ledger, [CmdbUser(public_id=USER.public_id, user_name='ann', active=True,
                                                       sync_pending=True)])

        assert calls == ['recorded', 'written']


def test_a_linked_object_is_inserted_under_a_counter_id_and_recorded() -> None:
    """The builder gets the new id; the insert is in the ledger"""
    context = _context(PersonSyncSettings())
    context.objects_manager.get_new_object_public_id.return_value = PERSON_ID
    ledger = MagicMock()

    assert insert_linked_object(context, ledger, lambda public_id: {'public_id': public_id}) == PERSON_ID

    context.objects_manager.insert.assert_called_once_with({'public_id': PERSON_ID}, id_from_counter=True)
    ledger.inserted.assert_called_once_with(context.objects_manager, PERSON_ID)


def test_the_mapped_groups_are_read_in_batches() -> None:
    """Two groups: one read each of the groups, the users, their persons and the Types - never per group (the groups
    hold no member, so no synced-member read)"""
    context = _context(PersonSyncSettings())
    groups: list[dict[str, Any]] = [
        {'public_id': group_id, 'type_id': 70, 'system_ref': {'kind': 'user_group', 'id': user_group_id},
         'fields': [{'name': 'name', 'value': 'n', 'type': 'text'}, {'name': 'members', 'value': [], 'type': 'person'}]}
        for group_id, user_group_id in ((80, 2), (81, 3))
    ]
    context.objects_manager.find.side_effect = [groups, []]
    context.groups_manager.get_groups.return_value = []
    context.users_manager.find.return_value = [{'public_id': USER.public_id, 'group_ids': [2, 3]}]
    context.types_manager.get_types_lookup.return_value = {}

    _sync_groups(context, WriteLedger(), {})

    context.users_manager.find.assert_called_once()
    context.users_manager.get_group_member_ids.assert_not_called()
    context.types_manager.get_types_lookup.assert_called_once_with([70])
    assert context.objects_manager.find.call_count == 2


def test_the_left_members_are_the_stored_ones_not_kept() -> None:
    """Ascending; recorded under the group's id only when someone left"""
    stored: dict[str, Any] = {'public_id': 80, 'fields': [{'name': 'members', 'value': [9, 3, 5]}]}
    result = SyncResult()

    assert left_synced_members(stored, [5, 7]) == [3, 9]

    record_left_members(result, stored, [9, 3, 5])
    assert not result.left_members

    record_left_members(result, stored, [5])
    assert result.left_members == {80: [3, 9]}


def test_merged_left_members_are_united_per_group() -> None:
    """Two calls taking persons out of one group name both"""
    first = SyncResult(left_members={80: [3]})

    first.merge(SyncResult(left_members={80: [9, 3], 81: [4]}))

    assert first.left_members == {80: [3, 9], 81: [4]}


def test_a_deleted_users_override_goes_given_a_settings_manager() -> None:
    """Whatever the switches; without a settings manager nothing touches the settings"""
    context = _context(PersonSyncSettings())
    context.objects_manager.find.return_value = []
    ledger = WriteLedger()

    with patch(f'{ENGINE_PATH}.drop_type_override') as drop:
        sync_user_deleted(context, ledger, USER.public_id)
        drop.assert_not_called()

        settings_manager = MagicMock()
        sync_user_deleted(replace(context, settings_manager=settings_manager), ledger, USER.public_id)

    drop.assert_called_once_with(settings_manager, ledger, USER.public_id)
