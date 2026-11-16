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
Unit tests for the membership rules of the person records layer (``person_records_helper``)

A person body's groups; the pre-check judging every group added or removed - none (400), unreadable or not updatable
(403) - before anything is written; the writes adding and removing the person, one group at a time
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.person_object_references import MarkedObjects
from cmdb.interface.rest_api.routes.user_management_routes import person_records_helper as module
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_TYPE: int = 7


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


@pytest.mark.parametrize('marker, body, expected', [
    (SpecialType.PERSON, {'groups': [2, 1, 2]}, {1, 2}),
    (SpecialType.PERSON, {'groups': None}, set()),
    (SpecialType.PERSON, {}, None),
    (SpecialType.PERSON_GROUP, {'groups': [1]}, None),
], ids=['set', 'null', 'absent', 'a-group'])
def test_the_selected_groups(marker: SpecialType, body: dict[str, Any], expected: Any) -> None:
    """Only a person body carrying groups changes membership"""
    assert module._selected_groups(marker, body) == expected  # pylint: disable=protected-access


@pytest.mark.parametrize('marked, denied_update, status', [
    (MarkedObjects(unknown=[5], unreadable=[]), [], HTTPStatus.BAD_REQUEST),
    (MarkedObjects(unknown=[], unreadable=[5]), [], HTTPStatus.FORBIDDEN),
    (MarkedObjects(unknown=[], unreadable=[]), [GROUP_TYPE], HTTPStatus.FORBIDDEN),
], ids=['none', 'unreadable', 'not-updatable'])
def test_a_changed_group_is_judged(flask_app: Flask, marked: MarkedObjects, denied_update: list[int],
                                   status: HTTPStatus) -> None:
    """Only the groups that change - added or removed - are asked"""
    context = _context({5: GROUP_TYPE})

    with flask_app.app_context(), \
            patch.object(module, 'resolve_marked_objects', return_value=marked) as resolve, \
            patch.object(module, 'hidden_types_of'), \
            patch.object(module, '_denied', return_value=denied_update), \
            pytest.raises(HTTPException) as caught:
        module._judge_membership(context, {4, 6}, {4, 5})  # pylint: disable=protected-access

    assert caught.value.code == status
    assert resolve.call_args.args[2] == {5, 6}


def test_an_unchanged_membership_passes_without_a_read(flask_app: Flask) -> None:
    """Nothing changes, nothing is judged"""
    context = _context()

    with flask_app.app_context(), \
            patch.object(module, 'resolve_marked_objects', return_value=MarkedObjects([], [])), \
            patch.object(module, 'hidden_types_of'), \
            patch.object(module, '_denied', return_value=[GROUP_TYPE]):
        module._judge_membership(context, {4}, {4})  # pylint: disable=protected-access

    context.objects_manager.find.assert_not_called()


def test_the_person_joins_and_leaves_one_group_at_a_time() -> None:
    """Added to the group it joins, taken out of the one it leaves; the others untouched"""
    joined, left = object(), object()
    stored: dict[int, Any] = {5: joined, 6: left}
    members: dict[Any, list[int]] = {joined: [1], left: [3, 9]}
    context = MagicMock()
    context.objects_manager.get_object.side_effect = lambda group_id, as_dict: stored[group_id]

    with patch.object(module.CmdbObject, 'to_json', side_effect=lambda group: {
                'public_id': 0, 'fields': [{'name': 'members', 'value': members[group]}]}), \
            patch.object(module, '_patch_fields') as patch_fields:
        module._write_membership(context, 9, {6}, {5})  # pylint: disable=protected-access

    assert [(call.args[1], call.args[2][0]['value']) for call in patch_fields.call_args_list] == [
        (joined, [1, 9]), (left, [3]),
    ]
