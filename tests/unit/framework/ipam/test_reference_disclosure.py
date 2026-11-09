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
Unit tests for cmdb.framework.ipam.reference_disclosure

What an IPAM refusal may say about the objects that caused it: the id description of a delete guard (readable ids,
then "and N more", then ", plus N object(s) you cannot see" - never reading as another id) and the caller's hidden
Types, read lazily and once. The module's names are pinned
"""
import inspect
from unittest.mock import MagicMock, patch

import pytest

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam import reference_disclosure
from cmdb.framework.ipam.reference_disclosure import describe_reference_ids, hidden_types_of, no_hidden_types
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.framework.ipam.reference_disclosure'
DENIED_TYPE_IDS: list[int] = [61, 62]


@pytest.mark.parametrize('listed, more, hidden, expected', [
    ([1, 2], 0, 0, '1, 2'),
    ([1, 2], 135, 0, '1, 2 and 135 more'),
    ([1], 0, 2, '1, plus 2 object(s) you cannot see'),
    ([1, 2], 135, 3, '1, 2 and 135 more, plus 3 object(s) you cannot see'),
    ([], 0, 3, '3 object(s) you cannot see'),
    ([], 0, 0, ''),
], ids=['listed', 'capped', 'listed-and-hidden', 'everything', 'hidden-only', 'nothing'])
def test_describe_reference_ids(listed: list[int], more: int, hidden: int, expected: str) -> None:
    """The hidden count never reads as another id"""
    assert describe_reference_ids(listed, more, hidden) == expected


def test_no_hidden_types_is_empty() -> None:
    """A caller nothing is hidden from"""
    assert no_hidden_types() == frozenset()


def test_hidden_types_are_read_lazily_and_once() -> None:
    """Nothing is read until asked; asked twice, read once; READ is the permission"""
    user = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids', return_value=DENIED_TYPE_IDS) as resolve:
        hidden = hidden_types_of(user)
        resolve.assert_not_called()

        assert hidden() == frozenset(DENIED_TYPE_IDS)
        assert hidden() == frozenset(DENIED_TYPE_IDS)

    resolve.assert_called_once_with(user, AccessControlPermission.READ)


def test_each_request_gets_its_own_read() -> None:
    """The cache belongs to the call hidden_types_of answered, not to the module"""
    with patch(f'{MODULE_PATH}.resolve_denied_type_ids', return_value=DENIED_TYPE_IDS) as resolve:
        hidden_types_of(MagicMock())()
        hidden_types_of(MagicMock())()

    assert resolve.call_count == 2


def test_the_module_names_are_pinned() -> None:
    """A new public name is a deliberate change"""
    functions: set[str] = {
        name for name, member in inspect.getmembers(reference_disclosure, inspect.isfunction)
        if member.__module__ == reference_disclosure.__name__
    }

    assert functions == {'describe_reference_ids', 'hidden_types_of', 'no_hidden_types'}
    assert set(reference_disclosure.__all__) == functions | {'HiddenTypeIds'}
