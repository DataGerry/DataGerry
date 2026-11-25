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
anything and each group's permission values
"""
from typing import Any

import pytest

from cmdb.security.acl.acl_groups import (
    acl_group_ids,
    acl_includes,
    granting_group_ids,
    group_key_id,
    group_permissions,
)
# -------------------------------------------------------------------------------------------------------------------- #

READ: str = 'READ'
UPDATE: str = 'UPDATE'
GROUP: int = 5
OTHER_GROUP: int = 7
UNGRANTED_GROUP: int = 8
HIGH_GROUP: int = 12
LOW_GROUP: int = 3

# The includes keys of those groups, as a stored block spells them
G: str = str(GROUP)
O: str = str(OTHER_GROUP)


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


class TestGroupKeyId:
    """group_key_id"""

    @pytest.mark.parametrize('key, expected', [(G, GROUP), (GROUP, GROUP), (str(HIGH_GROUP), HIGH_GROUP)],
                             ids=['string', 'int', 'two-digits'])
    def test_a_group_key(self, key: Any, expected: int) -> None:
        """A stored string or an in-memory int"""
        assert group_key_id(key) == expected

    @pytest.mark.parametrize('key', ['admin', '07', '0', '-5', '', ' 5', 0, -5, True, 5.0, None],
                             ids=['word', 'leading-zero', 'zero', 'negative', 'empty', 'space', 'int-zero',
                                  'int-negative', 'bool', 'float', 'none'])
    def test_a_key_that_is_no_group_id(self, key: Any) -> None:
        """None - the reader passes it over"""
        assert group_key_id(key) is None


class TestGroupPermissions:
    """group_permissions"""

    def test_each_group_with_its_values(self) -> None:
        """In stored order, whatever activated says"""
        expected: dict[int, list[str]] = {GROUP: [UPDATE, READ], OTHER_GROUP: []}

        assert group_permissions(_acl({G: [UPDATE, READ], O: []}, activated=False)) == expected

    def test_unreadable_entries_hold_nothing(self) -> None:
        """A key that is no group id is left out; a non-list holds nothing; a non-string value is passed over"""
        assert group_permissions(_acl({'admin': [READ], '07': [READ], G: READ, O: [READ, 7, None]})) == {
            GROUP: [], OTHER_GROUP: [READ]}

    def test_a_missing_block_names_nobody(self) -> None:
        """Never raises"""
        assert not group_permissions(None)
