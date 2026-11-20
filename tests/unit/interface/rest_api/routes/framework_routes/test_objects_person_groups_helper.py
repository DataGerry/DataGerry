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
Unit tests for the person's groups helper (``objects_person_groups_helper``)

The person read (404 for no person); the group pre-check - none (400), unreadable or not updatable (403); the change:
a group both added and removed (400), an empty change writing nothing, only the groups that change written - all at
once, with the membership change's undo message - each with the person added or taken out of its stored members
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.person_object_references import MarkedObjects
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects import objects_person_groups_helper as module
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    PERSON_GROUPS_RESIDUE_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_TYPE: int = 7
PERSON: int = 9
JOINED: int = 5
LEFT: int = 6


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A bare app for the abort context"""
    return Flask(__name__)


def _context(groups: dict[int, int] | None = None) -> MagicMock:
    """A write context whose objects manager finds the groups (id -> type id)"""
    context = MagicMock()
    context.objects_manager.find.return_value = [{'public_id': group_id, 'type_id': type_id}
                                                 for group_id, type_id in (groups or {}).items()]

    return context


class TestTheMarkedRead:
    """read_marked_object"""

    @pytest.mark.parametrize('stored', [None, MagicMock(special_type=SpecialType.PERSON_GROUP.value)],
                             ids=['missing', 'a-group'])
    def test_no_person_is_a_404(self, flask_app: Flask, stored: Any) -> None:
        """Only an object of the marker"""
        objects = MagicMock()
        objects.get_object.return_value = stored

        with flask_app.app_context(), \
                patch.object(module.ManagerProvider, 'get_manager', return_value=objects), \
                pytest.raises(HTTPException) as caught:
            module.read_marked_object(SpecialType.PERSON, PERSON, MagicMock())

        assert caught.value.code == HTTPStatus.NOT_FOUND

    def test_a_person_is_answered(self) -> None:
        """Read with the caller's READ"""
        objects = MagicMock()
        person = MagicMock(special_type=SpecialType.PERSON.value)
        objects.get_object.return_value = person

        with patch.object(module.ManagerProvider, 'get_manager', return_value=objects):
            assert module.read_marked_object(SpecialType.PERSON, PERSON, MagicMock()) is person

        assert objects.get_object.call_args.args[2] == module.AccessControlPermission.READ


class TestTheJudge:
    """judge_group_changes"""

    @pytest.mark.parametrize('marked, denied_update, status', [
        (MarkedObjects(unknown=[JOINED], unreadable=[]), [], HTTPStatus.BAD_REQUEST),
        (MarkedObjects(unknown=[], unreadable=[JOINED]), [], HTTPStatus.FORBIDDEN),
        (MarkedObjects(unknown=[], unreadable=[]), [GROUP_TYPE], HTTPStatus.FORBIDDEN),
    ], ids=['none', 'unreadable', 'not-updatable'])
    def test_a_group_is_refused(self, flask_app: Flask, marked: MarkedObjects, denied_update: list[int],
                                status: HTTPStatus) -> None:
        """Each group named is asked"""
        context = _context({JOINED: GROUP_TYPE})

        with flask_app.app_context(), \
                patch.object(module, 'resolve_marked_objects', return_value=marked) as resolve, \
                patch.object(module, 'hidden_types_of'), \
                patch.object(module, 'resolve_denied_type_ids', return_value=denied_update), \
                pytest.raises(HTTPException) as caught:
            module.judge_group_changes(context, {JOINED, LEFT})

        assert caught.value.code == status
        assert resolve.call_args.args[2] == {JOINED, LEFT}

    def test_updatable_groups_pass(self) -> None:
        """A group of another Type than the denied one"""
        context = _context({JOINED: GROUP_TYPE})

        with patch.object(module, 'resolve_marked_objects', return_value=MarkedObjects([], [])), \
                patch.object(module, 'hidden_types_of'), \
                patch.object(module, 'resolve_denied_type_ids', return_value=[GROUP_TYPE + 1]):
            module.judge_group_changes(context, {JOINED})

        context.objects_manager.find.assert_called_once()


class TestTheChange:
    """change_person_groups"""

    def test_a_group_both_added_and_removed_is_a_400(self, flask_app: Flask) -> None:
        """Before any group is judged"""
        with flask_app.app_context(), \
                patch.object(module, 'judge_group_changes') as judge, \
                pytest.raises(HTTPException) as caught:
            module.plan_membership_change(MagicMock(), set(), {JOINED, LEFT}, {LEFT})

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str([LEFT]) in caught.value.description
        judge.assert_not_called()

    def test_the_plan_names_what_joins_and_what_is_written(self) -> None:
        """Every named group judged; a group already as asked is no target"""
        context = MagicMock()

        with patch.object(module, 'judge_group_changes') as judge:
            change = module.plan_membership_change(context, {LEFT, 4}, {JOINED, 4}, {LEFT})

        judge.assert_called_once_with(context, {JOINED, 4, LEFT})
        assert change == module.MembershipChange(frozenset({JOINED, 4}), (JOINED, LEFT))

    def test_an_empty_change_reads_nothing(self) -> None:
        """No group named"""
        with patch.object(module.ObjectWriteContext, 'for_request') as for_request:
            module.change_person_groups(PERSON, set(), set(), MagicMock())

        for_request.assert_not_called()

    def test_only_the_changing_groups_are_written_at_once(self) -> None:
        """Every named group judged; the one already held not written; the undo message the change's own"""
        context = MagicMock()

        with patch.object(module.ObjectWriteContext, 'for_request', return_value=context), \
                patch.object(module, 'judge_group_changes') as judge, \
                patch.object(module, '_current_groups', return_value=[LEFT, 4]), \
                patch.object(module, 'apply_object_updates') as apply_updates:
            module.change_person_groups(PERSON, {JOINED, 4}, {LEFT}, MagicMock())

        judge.assert_called_once_with(context, {JOINED, 4, LEFT})
        assert apply_updates.call_args.args[0] == [JOINED, LEFT]
        assert apply_updates.call_args.args[2:] == (None, context)
        assert apply_updates.call_args.kwargs == {'residue_message': PERSON_GROUPS_RESIDUE_MESSAGE}

    def test_nothing_to_change_writes_nothing(self) -> None:
        """Every group already as asked"""
        with patch.object(module.ObjectWriteContext, 'for_request'), \
                patch.object(module, 'judge_group_changes'), \
                patch.object(module, '_current_groups', return_value=[JOINED]), \
                patch.object(module, 'apply_object_updates') as apply_updates:
            module.change_person_groups(PERSON, {JOINED}, {LEFT}, MagicMock())

        apply_updates.assert_not_called()


@pytest.mark.parametrize('group_id, expected', [(JOINED, [3, PERSON]), (LEFT, [3])], ids=['joins', 'leaves'])
def test_the_payload_changes_only_the_members(group_id: int, expected: list[int]) -> None:
    """The stored members, the person added or taken out; merged as a PATCH of that one field"""
    group = MagicMock()
    group.get_public_id.return_value = group_id
    group_type = MagicMock()
    group_type.get_mds_section_ids.return_value = {'rows'}
    stored_members: list[int] = [3] if group_id == JOINED else [3, PERSON]

    with patch.object(module.CmdbObject, 'to_json', return_value={
                'fields': [{'name': 'members', 'value': stored_members}]}), \
            patch.object(module, 'build_patched_object_data', return_value='merged') as merge:
        build = module._members_payload(PERSON, frozenset({JOINED}))  # pylint: disable=protected-access

        assert build(group, group_type) == 'merged'

    assert merge.call_args.args[1:] == ({'fields': [{'name': 'members', 'value': expected}]}, {'rows'})


class TestTheWrite:
    """write_membership_change"""

    @staticmethod
    def _object(public_id: int) -> MagicMock:
        """A stored object answering its id"""
        stored = MagicMock()
        stored.get_public_id.return_value = public_id

        return stored

    def test_the_person_is_written_first_with_its_own_payload(self) -> None:
        """One call, all or none: the person, then the groups - each with its own payload"""
        change = module.MembershipChange(frozenset({JOINED}), (JOINED, LEFT))
        person_payload = MagicMock(return_value='person')

        with patch.object(module, 'apply_object_updates') as apply_updates, \
                patch.object(module, '_members_payload', return_value=MagicMock(return_value='group')):
            module.write_membership_change(PERSON, change, MagicMock(), person_payload)

        targets, build = apply_updates.call_args.args[:2]
        assert targets == [PERSON, JOINED, LEFT]
        assert (build(self._object(PERSON), MagicMock()), build(self._object(JOINED), MagicMock())) == (
            'person', 'group')

    def test_without_a_person_payload_only_the_groups(self) -> None:
        """The person is left alone"""
        with patch.object(module, 'apply_object_updates') as apply_updates:
            module.write_membership_change(PERSON, module.MembershipChange(frozenset(), (LEFT,)), MagicMock())

        assert apply_updates.call_args.args[0] == [LEFT]

    def test_nothing_to_write(self) -> None:
        """No person payload, no target"""
        with patch.object(module, 'apply_object_updates') as apply_updates:
            module.write_membership_change(PERSON, module.MembershipChange(), MagicMock())

        apply_updates.assert_not_called()
