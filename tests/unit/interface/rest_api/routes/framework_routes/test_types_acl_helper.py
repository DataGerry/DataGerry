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
Unit tests for types_acl_helper.abort_if_unknown_acl_groups

A type create refuses every ACL group that does not exist; an update refuses only the groups the stored list does
not already name, so an entry an earlier group delete left behind does not make the type unsaveable
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_acl_helper import abort_if_unknown_acl_groups
from cmdb.interface.rest_api.routes.routes_helper import UNKNOWN_REFERENCES_MSG
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import USER_GROUP_LABEL
# -------------------------------------------------------------------------------------------------------------------- #

GROUP: int = 5
MISSING_GROUP: int = 99
STALE_GROUP: int = 98
READ: list[str] = ['READ']


def _acl(*group_ids: int) -> dict[str, Any]:
    """An acl block granting each group READ."""
    return {'activated': True, 'groups': {'includes': {str(group_id): READ for group_id in group_ids}}}


def _groups(existing: set[int]) -> MagicMock:
    """A stub GroupsManager answering which ids exist."""
    manager = MagicMock()
    manager.find_existing_public_ids.side_effect = lambda ids: set(ids) & existing

    return manager


def test_a_create_with_existing_groups_passes() -> None:
    """The ordinary case"""
    abort_if_unknown_acl_groups({'acl': _acl(GROUP)}, _groups({GROUP}))


def test_a_create_naming_a_missing_group_is_refused() -> None:
    """By id"""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_unknown_acl_groups({'acl': _acl(GROUP, MISSING_GROUP)}, _groups({GROUP}))

    assert exc_info.value.code == 400
    assert exc_info.value.description == UNKNOWN_REFERENCES_MSG.format(entity_label=USER_GROUP_LABEL,
                                                                       unknown=[MISSING_GROUP])


def test_an_update_keeping_a_stale_stored_entry_passes() -> None:
    """Only what the stored list does not name is judged - and not even read"""
    groups = _groups({GROUP})

    abort_if_unknown_acl_groups({'acl': _acl(GROUP, STALE_GROUP)}, groups, stored_acl=_acl(GROUP, STALE_GROUP))

    groups.find_existing_public_ids.assert_not_called()


def test_an_update_adding_a_missing_group_is_refused() -> None:
    """Next to the stale entry it keeps"""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_unknown_acl_groups({'acl': _acl(STALE_GROUP, MISSING_GROUP)}, _groups({GROUP}),
                                    stored_acl=_acl(STALE_GROUP))

    assert str(MISSING_GROUP) in exc_info.value.description
    assert str(STALE_GROUP) not in exc_info.value.description


@pytest.mark.parametrize('type_data', [{}, {'acl': None}, {'acl': {'activated': False}}],
                         ids=['no-acl', 'null-acl', 'no-groups'])
def test_an_acl_naming_no_group_reads_nothing(type_data: dict[str, Any]) -> None:
    """Nothing to check"""
    groups = _groups(set())

    abort_if_unknown_acl_groups(type_data, groups)

    groups.find_existing_public_ids.assert_not_called()
