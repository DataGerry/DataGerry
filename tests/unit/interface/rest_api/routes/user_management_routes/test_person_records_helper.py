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

A person body's groups; an update planning the groups added and removed from the readable groups held, then writing
the person and its groups in one all-or-none write; the record's fields payload
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey
from cmdb.interface.rest_api.routes.user_management_routes import person_records_helper as module
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_TYPE: int = 7
PERSON: int = 9


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A bare app for the abort context"""
    return Flask(__name__)


@pytest.mark.parametrize('marker, body, expected', [
    (SpecialType.PERSON, {'groups': [2, 1, 2]}, {1, 2}),
    (SpecialType.PERSON, {'groups': None}, set()),
    (SpecialType.PERSON, {}, None),
    (SpecialType.PERSON_GROUP, {'groups': [1]}, None),
], ids=['set', 'null', 'absent', 'a-group'])
def test_the_selected_groups(marker: SpecialType, body: dict[str, Any], expected: Any) -> None:
    """Only a person body carrying groups changes membership"""
    assert module._selected_groups(marker, body) == expected  # pylint: disable=protected-access


@pytest.mark.parametrize('selected, add, remove', [
    ([4, 5], {5}, {6}), ([], set(), {4, 6}),
], ids=['joins-and-leaves', 'leaves-all'])
def test_an_update_writes_the_person_and_its_groups_at_once(selected: list[int], add: set[int],
                                                           remove: set[int]) -> None:
    """The change planned from the readable groups held, then one write: the person with its fields, the groups"""
    stored = MagicMock()
    stored.get_public_id.return_value = PERSON
    context = MagicMock()

    with patch.object(module, 'read_marked_object', return_value=stored), \
            patch.object(module.ObjectWriteContext, 'for_request', return_value=context), \
            patch.object(module, 'groups_of_persons', return_value={PERSON: [4, 6]}), \
            patch.object(module, '_denied'), \
            patch.object(module, 'plan_membership_change', return_value='the change') as plan, \
            patch.object(module, 'write_membership_change') as write:
        module.update_record(SpecialType.PERSON, PERSON, {'groups': selected, 'phone_number': '1'}, MagicMock())

    plan.assert_called_once_with(context, {4, 6}, add, remove)
    assert write.call_args.args[:3] == (PERSON, 'the change', context)
    assert write.call_args.args[3] is not None


def test_an_update_without_groups_writes_the_record_alone() -> None:
    """No group read, no plan - the empty change"""
    stored = MagicMock()
    stored.get_public_id.return_value = PERSON

    with patch.object(module, 'read_marked_object', return_value=stored), \
            patch.object(module.ObjectWriteContext, 'for_request'), \
            patch.object(module, 'groups_of_persons') as groups, \
            patch.object(module, 'write_membership_change') as write:
        module.update_record(SpecialType.PERSON, PERSON, {'phone_number': '1'}, MagicMock())

    groups.assert_not_called()
    assert write.call_args.args[1] == module.MembershipChange()


def test_the_fields_payload_sets_the_record_keys() -> None:
    """Merged as a PATCH, the multi-data sections of the Type passed on"""
    current_type = MagicMock()
    current_type.get_mds_section_ids.return_value = {'rows'}
    entries: list[dict[str, Any]] = [{'name': 'phone_number', 'value': '1'}]

    with patch.object(module, 'build_patched_object_data', return_value='merged') as merge:
        assert module._fields_payload(entries)('stored', current_type) == 'merged'  # pylint: disable=protected-access

    merge.assert_called_once_with('stored', {'fields': entries}, {'rows'})


@pytest.mark.parametrize('marker', [SpecialType.PERSON, SpecialType.PERSON_GROUP], ids=['person', 'group'])
def test_no_default_type_is_a_400_naming_the_record(flask_app: Flask, marker: SpecialType) -> None:
    """A system the person migration never ran on has no default Type: the create is refused, never a 500"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with flask_app.app_context(), \
            patch.object(module.ManagerProvider, 'get_manager', return_value=types_manager), \
            pytest.raises(HTTPException) as caught:
        module._default_type(marker, MagicMock())  # pylint: disable=protected-access

    assert caught.value.code == HTTPStatus.BAD_REQUEST
    assert caught.value.description == module.DEFAULT_TYPE_MISSING_MESSAGE.format(label=module.RECORD_LABELS[marker])
    types_manager.get_one_by.assert_called_once_with({
        TypeSchemaKey.SPECIAL_TYPE.value: marker.value, TypeSchemaKey.SYSTEM_TYPE.value: True,
    })


def test_the_default_type_is_the_system_type_of_the_marker(flask_app: Flask) -> None:
    """Only the system Type is asked for - an ordinary Type carrying the marker is never the default"""
    types_manager = MagicMock()
    stored: dict[str, Any] = {TypeSchemaKey.PUBLIC_ID.value: GROUP_TYPE}
    types_manager.get_one_by.return_value = stored

    with flask_app.app_context(), \
            patch.object(module.ManagerProvider, 'get_manager', return_value=types_manager), \
            patch.object(module.CmdbType, 'from_data', return_value='the type') as from_data:
        assert module._default_type(SpecialType.PERSON, MagicMock()) == 'the type'  # pylint: disable=protected-access

    from_data.assert_called_once_with(stored)
