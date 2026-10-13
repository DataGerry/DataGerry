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
Unit tests for cmdb.models.location_model.location_visibility

A node is as visible as its object: hidden when its own Type is denied, and a hidden node hides its whole branch
"""
from typing import Any

import pytest

from cmdb.models.location_model import chain_is_hidden, node_is_hidden
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE: int = 7
OTHER_TYPE: int = 8
ROOT_TYPE: int = 0


def _node(type_id: Any) -> dict[str, Any]:
    """A location document of the given type."""
    return {'public_id': 1, 'type_id': type_id}


class TestNodeIsHidden:
    """node_is_hidden"""

    def test_a_node_of_a_denied_type(self) -> None:
        """Hidden"""
        assert node_is_hidden(_node(DENIED_TYPE), [DENIED_TYPE])

    @pytest.mark.parametrize('node', [_node(OTHER_TYPE), _node(ROOT_TYPE), {'public_id': 1}],
                             ids=['other-type', 'root', 'no-type'])
    def test_any_other_node(self, node: dict[str, Any]) -> None:
        """Shown"""
        assert not node_is_hidden(node, [DENIED_TYPE])


class TestChainIsHidden:
    """chain_is_hidden"""

    def test_the_node_itself_hidden(self) -> None:
        """First in the chain"""
        assert chain_is_hidden([_node(DENIED_TYPE), _node(ROOT_TYPE)], [DENIED_TYPE])

    def test_an_ancestor_hidden_hides_the_branch(self) -> None:
        """A readable node below a hidden one is hidden too"""
        assert chain_is_hidden([_node(OTHER_TYPE), _node(DENIED_TYPE), _node(ROOT_TYPE)], [DENIED_TYPE])

    def test_a_readable_chain(self) -> None:
        """Nothing denied on it"""
        assert not chain_is_hidden([_node(OTHER_TYPE), _node(ROOT_TYPE)], [DENIED_TYPE])

    @pytest.mark.parametrize('denied', [[], set(), ()], ids=['list', 'set', 'tuple'])
    def test_no_denial_hides_nothing(self, denied: Any) -> None:
        """The admin's view"""
        assert not chain_is_hidden([_node(DENIED_TYPE)], denied)

    def test_an_empty_chain_is_not_hidden(self) -> None:
        """A node that does not exist - the route answers that case itself"""
        assert not chain_is_hidden([], [DENIED_TYPE])
