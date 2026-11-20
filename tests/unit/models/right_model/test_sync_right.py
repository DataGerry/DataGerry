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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests of the user sync right (``base.user-management.sync.edit``)

Pinned: the right and its wildcard are in the catalogue, inside the user management branch; the right is granted by
its own wildcard, by ``base.user-management.*`` and by the master right ``base.*`` - so the administrators hold it -
but not by the user or the user group wildcards. Pure: no Mongo, no Flask
"""
import pytest

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.all_rights import ALL_RIGHTS_FLAT, USER_MANAGEMENT_RIGHTS, flat_rights_tree
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.user_management_rights import SyncRight, UserManagementRight
# -------------------------------------------------------------------------------------------------------------------- #

SYNC_EDIT: str = 'base.user-management.sync.edit'
SYNC_WILDCARD: str = 'base.user-management.sync.*'
SYNC_EDIT_LABEL: str = 'sync.edit'
GROUP_ID: int = 7
GROUP_NAME: str = 'sync-right-group'

GRANTING_RIGHTS: list[str] = ['base.*', 'base.user-management.*', SYNC_WILDCARD, SYNC_EDIT]
NOT_GRANTING_RIGHTS: list[str] = ['base.user-management.user.*', 'base.user-management.group.*',
                                  'base.framework.*']


def _catalogue_right(name: str) -> BaseRight:
    """The catalogue's right of that name"""
    return next(right for right in ALL_RIGHTS_FLAT if right.name == name)


def _group_holding(name: str) -> CmdbUserGroup:
    """A user group holding just the catalogue's right of that name"""
    return CmdbUserGroup(public_id=GROUP_ID, name=GROUP_NAME, rights=[_catalogue_right(name)])


class TestTheCatalogue:
    """Where the right sits."""

    def test_the_right_and_its_wildcard_are_offered(self) -> None:
        """Both names are in the flat catalogue the rights routes and the group screens read"""
        names: set[str] = {right.name for right in ALL_RIGHTS_FLAT}

        assert {SYNC_EDIT, SYNC_WILDCARD} <= names

    def test_they_sit_in_the_user_management_branch(self) -> None:
        """The rights picker shows them under user management"""
        branch_names: set[str] = {right.name for right in flat_rights_tree(USER_MANAGEMENT_RIGHTS)}

        assert {SYNC_EDIT, SYNC_WILDCARD} <= branch_names

    def test_the_family_names_and_labels_the_right(self) -> None:
        """Built name-first from the sync family, like every catalogue right"""
        right: BaseRight = _catalogue_right(SYNC_EDIT)

        assert isinstance(right, SyncRight) and issubclass(SyncRight, UserManagementRight)
        assert right.label == SYNC_EDIT_LABEL
        assert right.description


class TestWhoHoldsIt:
    """The wildcards above it grant it; the sibling families do not."""

    @pytest.mark.parametrize('held', GRANTING_RIGHTS)
    def test_it_is_granted(self, held: str) -> None:
        """The master right - the administrators' - included"""
        group: CmdbUserGroup = _group_holding(held)

        assert group.has_right(SYNC_EDIT) or group.has_extended_right(SYNC_EDIT)

    @pytest.mark.parametrize('held', NOT_GRANTING_RIGHTS)
    def test_it_is_not_granted(self, held: str) -> None:
        """Managing users or user groups is not configuring the sync"""
        group: CmdbUserGroup = _group_holding(held)

        assert not group.has_right(SYNC_EDIT) and not group.has_extended_right(SYNC_EDIT)
