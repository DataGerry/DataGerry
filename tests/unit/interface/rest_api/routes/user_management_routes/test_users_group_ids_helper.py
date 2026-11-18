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
Unit tests of the group-list helpers of cmdb.interface.rest_api.routes.user_management_routes.users_helper

Pinned: an administrator is a member of the administrator group wherever it stands in the list; a payload names the
administrator group when its list holds it; the canonical payload sorts and de-duplicates the list into a new dict and
a new list, leaving the given payload as it was - so a reordered list is no change for the field guards
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    guard_administrator_create,
    guard_user_update,
    is_administrator,
    names_administrator_group,
    with_canonical_group_ids,
)
from cmdb.models.group_model import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.user_model import CmdbUser, CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #

KEY: str = CmdbUserKey.GROUP_IDS.value
TARGET_ID: int = 51
DELEGATE_ID: int = 52
OTHER_GROUP_ID: int = 88


def _user(public_id: int, group_ids: list[int]) -> CmdbUser:
    """An in-memory user"""
    return CmdbUser(public_id=public_id, user_name=f'user-{public_id}', active=True, group_ids=group_ids)


@pytest.mark.parametrize('group_ids, expected', [
    ([ADMIN_GROUP_ID], True), ([ADMIN_GROUP_ID, OTHER_GROUP_ID], True), ([USER_GROUP_ID, OTHER_GROUP_ID], False),
], ids=['admin-only', 'admin-among-others', 'no-admin'])
def test_an_administrator_is_a_member_of_the_admin_group(group_ids: list[int], expected: bool) -> None:
    """Membership, not the first entry"""
    assert is_administrator(_user(TARGET_ID, group_ids)) is expected


@pytest.mark.parametrize('payload, expected', [
    ({KEY: [OTHER_GROUP_ID, ADMIN_GROUP_ID]}, True), ({KEY: [OTHER_GROUP_ID]}, False),
    ({}, False), ({KEY: None}, False),
], ids=['admin-second', 'no-admin', 'no-key', 'null'])
def test_a_payload_names_the_admin_group_when_its_list_holds_it(payload: dict[str, Any], expected: bool) -> None:
    """Wherever it stands"""
    assert names_administrator_group(payload) is expected


def test_a_non_administrator_cannot_create_an_administrator_by_listing_the_group_second() -> None:
    """The create guard reads the whole list (403)"""
    delegate = _user(DELEGATE_ID, [OTHER_GROUP_ID])

    with pytest.raises(HTTPException) as refused:
        guard_administrator_create(delegate, {KEY: [USER_GROUP_ID, ADMIN_GROUP_ID]})

    assert refused.value.code == 403


def test_the_canonical_payload_is_a_new_dict_with_a_new_sorted_list() -> None:
    """The given payload and its list stay as they were"""
    given_list: list[int] = [OTHER_GROUP_ID, USER_GROUP_ID, OTHER_GROUP_ID]
    payload: dict[str, Any] = {KEY: given_list, CmdbUserKey.ACTIVE.value: True}

    canonical = with_canonical_group_ids(payload)

    assert canonical == {KEY: [USER_GROUP_ID, OTHER_GROUP_ID], CmdbUserKey.ACTIVE.value: True}
    assert payload[KEY] is given_list and given_list == [OTHER_GROUP_ID, USER_GROUP_ID, OTHER_GROUP_ID]


def test_a_reordered_list_is_no_change_for_a_self_edit() -> None:
    """A user without the edit right may send their groups back in another order"""
    stored = _user(TARGET_ID, [USER_GROUP_ID, OTHER_GROUP_ID])
    body = with_canonical_group_ids({**CmdbUser.to_json(stored), KEY: [OTHER_GROUP_ID, USER_GROUP_ID]})
    body.pop(CmdbUserKey.PASSWORD.value)

    guard_user_update(stored, body, may_administer=False)
