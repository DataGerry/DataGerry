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
Unit tests for the reader-scoped reads of cmdb.manager.locations_manager

Each read narrowed by ``denied_type_ids``: the children and the has-children grouping leave denied nodes out, the
search drops a match whose chain is hidden, the path's sibling levels leave denied nodes out, the flat list goes
through the ACL criteria, and ``get_location_chain`` answers the node then its ancestors
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.locations_manager import LocationsManager, visible_criteria
from cmdb.manager.query_builder import BuilderParameters
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE: int = 7
OTHER_TYPE: int = 8
PARENT_ID: int = 3
NODE_ID: int = 10
HIDDEN_ANCESTOR_ID: int = 5
VISIBLE_ID: int = 11
DENIAL: dict[str, Any] = {'type_id': {'$nin': [DENIED_TYPE]}}


def _manager() -> MagicMock:
    """A MagicMock standing in for a LocationsManager instance."""
    return MagicMock(spec=LocationsManager)


class TestVisibleCriteria:
    """visible_criteria"""

    def test_adds_the_denial(self) -> None:
        """Next to the given criteria"""
        assert visible_criteria({'parent': PARENT_ID}, [DENIED_TYPE]) == {'parent': PARENT_ID, **DENIAL}

    def test_no_denial_keeps_the_criteria(self) -> None:
        """The admin's read"""
        criteria = {'parent': PARENT_ID}

        assert visible_criteria(criteria, ()) is criteria


class TestScopedLevelReads:
    """get_child_location_documents, get_parents_with_children, get_locations_on_path_to"""

    def test_children_leave_denied_nodes_out(self) -> None:
        """In the query"""
        manager = _manager()
        manager.get_many.return_value = []

        LocationsManager.get_child_location_documents(manager, PARENT_ID, [DENIED_TYPE])

        manager.get_many.assert_called_once_with(criteria={'parent': PARENT_ID, **DENIAL})

    def test_a_hidden_child_does_not_count_as_a_child(self) -> None:
        """The grouping's match carries the denial"""
        manager = _manager()
        manager.aggregate.return_value = []

        LocationsManager.get_parents_with_children(manager, [PARENT_ID], [DENIED_TYPE])

        assert manager.aggregate.call_args.args[0][0] == {'$match': {'parent': {'$in': [PARENT_ID]}, **DENIAL}}

    def test_the_path_levels_leave_denied_siblings_out(self) -> None:
        """The sibling read carries the denial"""
        manager = _manager()
        manager.aggregate.return_value = [{'ancestors': [{'public_id': PARENT_ID}]}]
        manager.get_many.return_value = []

        LocationsManager.get_locations_on_path_to(manager, NODE_ID, [DENIED_TYPE])

        criteria: dict[str, Any] = manager.get_many.call_args.kwargs['criteria']
        assert criteria['type_id'] == {'$nin': [DENIED_TYPE]}


class TestScopedSearch:
    """search_locations_with_ancestors"""

    def test_a_match_below_a_hidden_node_is_dropped_with_its_chain(self) -> None:
        """Neither the hidden ancestor nor the readable match is found; another match is"""
        manager = _manager()
        hidden = {'public_id': HIDDEN_ANCESTOR_ID, 'name': 'hidden', 'parent': 1, 'type_id': DENIED_TYPE}
        manager.aggregate.return_value = [
            {'public_id': NODE_ID, 'name': 'srv-a', 'parent': HIDDEN_ANCESTOR_ID, 'type_id': OTHER_TYPE,
             'ancestors': [hidden]},
            {'public_id': VISIBLE_ID, 'name': 'srv-b', 'parent': 1, 'type_id': OTHER_TYPE, 'ancestors': []},
        ]

        result = LocationsManager.search_locations_with_ancestors(manager, 'srv', [DENIED_TYPE])

        assert [location['public_id'] for location in result] == [VISIBLE_ID]

    def test_a_hidden_match_itself_is_dropped(self) -> None:
        """Not found by name"""
        manager = _manager()
        manager.aggregate.return_value = [
            {'public_id': NODE_ID, 'name': 'secret', 'parent': 1, 'type_id': DENIED_TYPE, 'ancestors': []}]

        assert not LocationsManager.search_locations_with_ancestors(manager, 'secret', [DENIED_TYPE])


class TestFlatList:
    """iterate_location_documents"""

    def test_the_reader_narrows_the_criteria(self) -> None:
        """Rows and total alike - through the shared ACL hook"""
        manager = _manager()
        manager.iterate_query.return_value = ([], 0)
        params, user = BuilderParameters(criteria={}), MagicMock()

        LocationsManager.iterate_location_documents(manager, params, user, AccessControlPermission.READ)

        manager.apply_acl_to_builder_params.assert_called_once_with(params, user, AccessControlPermission.READ)


class TestGetLocationChain:
    """get_location_chain"""

    def test_the_node_then_its_ancestors_projected(self) -> None:
        """One $graphLookup, two keys"""
        manager = _manager()
        manager.aggregate.return_value = [
            {'public_id': NODE_ID, 'type_id': OTHER_TYPE, 'ancestors': [{'public_id': 1, 'type_id': 0}]}]

        chain = LocationsManager.get_location_chain(manager, NODE_ID)

        assert chain == [{'public_id': NODE_ID, 'type_id': OTHER_TYPE}, {'public_id': 1, 'type_id': 0}]
        pipeline = manager.aggregate.call_args.args[0]
        assert pipeline[0] == {'$match': {'public_id': NODE_ID}}
        assert pipeline[-1]['$project'] == {'_id': 0, 'public_id': 1, 'type_id': 1,
                                            'ancestors.public_id': 1, 'ancestors.type_id': 1}

    def test_a_missing_node_is_an_empty_chain(self) -> None:
        """Nothing to judge"""
        manager = _manager()
        manager.aggregate.return_value = []

        assert not LocationsManager.get_location_chain(manager, NODE_ID)

    @pytest.mark.parametrize('error', [BaseManagerIterationError('down'), RuntimeError('bug')],
                             ids=['iteration-error', 'anything-else'])
    def test_a_failed_read_is_a_get_error_carrying_the_cause(self, error: Exception) -> None:
        """Wrapped with the exception itself"""
        manager = _manager()
        manager.aggregate.side_effect = error

        with pytest.raises(LocationsManagerGetError) as exc_info:
            LocationsManager.get_location_chain(manager, NODE_ID)

        assert exc_info.value.__cause__ is error
