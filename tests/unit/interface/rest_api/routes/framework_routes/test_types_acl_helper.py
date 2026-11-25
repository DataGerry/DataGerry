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
Unit tests for types_acl_helper - a type write may carry its acl only unchanged

A create accepts no acl or one meaning the default and stores the default; an update accepts no acl or one meaning
the block the access rules decide and keeps the stored block. What a block means ignores the permission order, groups
holding nothing and the groups of a switched-off block. Anything else is a 400
"""
from types import SimpleNamespace
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_acl_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_acl_helper import (
    acl_meaning,
    guard_created_acl,
    guard_updated_acl,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE,
)
from cmdb.security.acl.access_control_list import AccessControlList
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 11
GROUP: int = 5
OTHER_GROUP: int = 7
DEFAULT: dict[str, Any] = {'activated': False, 'groups': {'includes': {}}}
STORED: dict[str, Any] = {'activated': True, 'groups': {'includes': {'99': ['READ']}}}
DECIDED: dict[str, Any] = {'activated': True, 'groups': {'includes': {str(GROUP): ['READ', 'UPDATE']}}}


def _acl(includes: dict[int, list[str]], activated: bool = True) -> dict[str, Any]:
    """An acl block"""
    return {'activated': activated, 'groups': {'includes': {str(key): value for key, value in includes.items()}}}


class TestMeaning:
    """acl_meaning"""

    def test_order_and_empty_groups_do_not_count(self) -> None:
        """Same permissions, other order, one empty group"""
        assert acl_meaning(_acl({GROUP: ['UPDATE', 'READ'], OTHER_GROUP: []})) == acl_meaning(DECIDED)

    @pytest.mark.parametrize('acl', [None, 'x', DEFAULT, _acl({GROUP: ['READ']}, activated=False)],
                             ids=['none', 'not-a-dict', 'default', 'off-with-groups'])
    def test_every_switched_off_block_means_the_same(self, acl: Any) -> None:
        """The groups of a switched-off block are ignored"""
        assert acl_meaning(acl) == (False, {})

    def test_another_permission_is_another_meaning(self) -> None:
        """DELETE added"""
        assert acl_meaning(_acl({GROUP: ['READ', 'UPDATE', 'DELETE']})) != acl_meaning(DECIDED)


class TestCreate:
    """guard_created_acl"""

    @pytest.mark.parametrize('data', [{}, {'acl': DEFAULT}, {'acl': _acl({GROUP: ['READ']}, activated=False)}],
                             ids=['absent', 'default', 'off-with-groups'])
    def test_the_default_is_accepted_and_stored(self, data: dict[str, Any]) -> None:
        """Whatever spelling - the complete default is stored"""
        guard_created_acl(data)

        assert data['acl'] == AccessControlList.default_json()

    def test_an_activated_acl_is_refused(self) -> None:
        """400 - access is managed elsewhere"""
        with pytest.raises(HTTPException) as caught:
            guard_created_acl({'acl': _acl({GROUP: ['READ']})})

        assert (caught.value.code, caught.value.description) == (400, TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE)


class TestUpdate:
    """guard_updated_acl"""

    @staticmethod
    def _old_type() -> Any:
        """A stored Type whose stored acl differs from the decided one"""
        return SimpleNamespace(public_id=TYPE_ID, acl=AccessControlList.from_data(STORED))

    @pytest.fixture(name='asked')
    def fixture_decided(self, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        """The access rules decide DECIDED for the Type; the calls recorded"""
        asked: list[Any] = []
        monkeypatch.setattr(types_acl_helper, 'synthesised_acl_values',
                            lambda user, ids: asked.append((user, list(ids))) or {TYPE_ID: DECIDED})

        return asked

    def test_the_decided_block_sent_back_is_accepted_and_the_stored_kept(self, asked: list[Any]) -> None:
        """Another order of the same permissions; the stored block is what is written"""
        data: dict[str, Any] = {'acl': _acl({GROUP: ['UPDATE', 'READ']})}

        guard_updated_acl(data, self._old_type(), 'the-user')

        assert asked == [('the-user', [TYPE_ID])]
        assert data['acl'] == AccessControlList.to_json(AccessControlList.from_data(STORED))

    def test_no_acl_reads_nothing_and_keeps_the_stored(self, asked: list[Any]) -> None:
        """Nothing to judge"""
        data: dict[str, Any] = {}

        guard_updated_acl(data, self._old_type(), 'the-user')

        assert asked == [] and data['acl']['groups']['includes'] == {'99': ['READ']}

    @pytest.mark.parametrize('acl', [STORED, DEFAULT, _acl({GROUP: ['READ']})], ids=['stored', 'default', 'less'])
    def test_any_other_block_is_refused(self, asked: list[Any], acl: dict[str, Any]) -> None:
        """Even the stored one - it is not what the Type answers"""
        data: dict[str, Any] = {'acl': acl}

        with pytest.raises(HTTPException) as caught:
            guard_updated_acl(data, self._old_type(), 'the-user')

        assert caught.value.code == 400 and data['acl'] is acl
