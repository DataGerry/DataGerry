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
Unit tests for cmdb.security.acl.acl_groups

The group questions about a raw ``acl`` block: the ``includes`` mapping, the groups it names, the groups it grants
anything, and whether one group is the only existing group an activated block grants
"""
from typing import Any

import pytest

from cmdb.security.acl.acl_groups import acl_group_ids, acl_includes, granting_group_ids, is_sole_grantee
# -------------------------------------------------------------------------------------------------------------------- #

READ: str = 'READ'
UPDATE: str = 'UPDATE'
GROUP: int = 5
OTHER_GROUP: int = 7
DELETED_GROUP: int = 9
UNGRANTED_GROUP: int = 8
HIGH_GROUP: int = 12
LOW_GROUP: int = 3

# The includes keys of those groups, as a stored block spells them
G: str = str(GROUP)
O: str = str(OTHER_GROUP)
D: str = str(DELETED_GROUP)


def _acl(includes: Any, activated: bool = True) -> dict[str, Any]:
    """A stored acl block."""
    return {'activated': activated, 'groups': {'includes': includes}}


class TestAclIncludes:
    """acl_includes"""

    def test_answers_the_mapping(self) -> None:
        """The ordinary block"""
        assert acl_includes(_acl({G: [READ]})) == {G: [READ]}

    @pytest.mark.parametrize('acl', [None, 'x', {}, {'groups': None}, {'groups': {'includes': None}},
                                     {'groups': {'includes': [G]}}],
                             ids=['none', 'string', 'empty', 'groups-null', 'includes-null', 'includes-list'])
    def test_a_missing_or_malformed_level_is_empty(self, acl: Any) -> None:
        """Never raises"""
        assert not acl_includes(acl)


class TestAclGroupIds:
    """acl_group_ids"""

    def test_every_named_group_sorted_whatever_it_grants(self) -> None:
        """An empty permission list still names the group"""
        assert acl_group_ids(_acl({str(HIGH_GROUP): [], str(LOW_GROUP): [READ]})) == [LOW_GROUP, HIGH_GROUP]

    @pytest.mark.parametrize('key', ['0', '05', '-1', 'x', '1.5', ' 5'],
                             ids=['zero', 'leading-zero', 'negative', 'letter', 'decimal', 'padded'])
    def test_a_key_the_schema_would_refuse_names_no_group(self, key: str) -> None:
        """The type write schema's key rule"""
        assert not acl_group_ids(_acl({key: [READ]}))


class TestGrantingGroupIds:
    """granting_group_ids"""

    def test_only_groups_with_a_permission(self) -> None:
        """An empty list grants nothing"""
        assert granting_group_ids(_acl({G: [READ], O: [], str(UNGRANTED_GROUP): None})) == {GROUP}


class TestIsSoleGrantee:
    """is_sole_grantee"""

    def test_the_only_granted_group(self) -> None:
        """Deleting it would lock the type"""
        assert is_sole_grantee(_acl({G: [READ, UPDATE]}), GROUP, [GROUP, OTHER_GROUP])

    def test_not_while_another_existing_group_is_granted(self) -> None:
        """The other group can still reach the type"""
        assert not is_sole_grantee(_acl({G: [READ], O: [READ]}), GROUP, [GROUP, OTHER_GROUP])

    def test_a_grant_to_a_deleted_group_does_not_count(self) -> None:
        """It grants nobody"""
        assert is_sole_grantee(_acl({G: [READ], D: [READ]}), GROUP, [GROUP, OTHER_GROUP])

    def test_another_group_with_no_permission_does_not_count(self) -> None:
        """Named, but granted nothing"""
        assert is_sole_grantee(_acl({G: [READ], O: []}), GROUP, [GROUP, OTHER_GROUP])

    def test_a_list_that_is_not_activated_grants_everyone(self) -> None:
        """No group is its sole grantee"""
        assert not is_sole_grantee(_acl({G: [READ]}, activated=False), GROUP, [GROUP])

    def test_a_group_the_list_grants_nothing_is_not_its_grantee(self) -> None:
        """Named with an empty list"""
        assert not is_sole_grantee(_acl({G: []}), GROUP, [GROUP])

    @pytest.mark.parametrize('acl', [None, {'activated': 'true', 'groups': {'includes': {G: [READ]}}}],
                             ids=['none', 'activated-not-a-boolean'])
    def test_only_an_activated_boolean_counts(self, acl: Any) -> None:
        """The stored shape is a boolean since updater_20261001"""
        assert not is_sole_grantee(acl, GROUP, [GROUP])
