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
Unit tests for BuilderParameters

The accessors are plain reads; what is worth pinning is ``add_criteria``, the one place a route
narrows a query the CLIENT supplied. Two properties are behaviour, not detail: the server's
condition goes FIRST in a pipeline (so no client stage can change what it decides), and it never
overwrites a key the client already used.
"""
from cmdb.manager.query_builder import BuilderParameters
# -------------------------------------------------------------------------------------------------------------------- #

CONDITION: dict = {'public_id': {'$in': [1, 2]}}


def _params(criteria) -> BuilderParameters:
    """A BuilderParameters carrying the given criteria and nothing else of interest."""
    return BuilderParameters(criteria=criteria, limit=10, skip=0, sort='public_id', order=1)


# ----------------------------------------------------- dict criteria ------------------------------------------------ #

def test_add_criteria_on_an_empty_dict_becomes_the_condition() -> None:
    """An unfiltered query simply gains the condition."""
    params = _params({})

    params.add_criteria(CONDITION)

    assert params.get_criteria() == CONDITION


def test_add_criteria_merges_into_a_dict_without_colliding_keys() -> None:
    """Disjoint keys merge flat - no needless $and wrapper."""
    params = _params({'active': True})

    params.add_criteria(CONDITION)

    assert params.get_criteria() == {'active': True, **CONDITION}


def test_add_criteria_wraps_a_colliding_key_in_and_instead_of_overwriting() -> None:
    """A key the client already used survives: both conditions have to hold."""
    client_condition = {'public_id': 7}
    params = _params(dict(client_condition))

    params.add_criteria(CONDITION)

    assert params.get_criteria() == {'$and': [client_condition, CONDITION]}


def test_add_criteria_never_drops_the_clients_condition() -> None:
    """Whatever the shape, the client's own filter is still in the criteria afterwards."""
    params = _params({'public_id': 7})

    params.add_criteria(CONDITION)

    assert 'public_id' in str(params.get_criteria())
    assert '7' in str(params.get_criteria())


def test_add_criteria_does_not_mutate_the_condition_it_was_given() -> None:
    """The caller's condition dict is copied, not adopted."""
    condition = {'a': 1}
    params = _params({})

    params.add_criteria(condition)
    params.criteria['b'] = 2

    assert condition == {'a': 1}


# ----------------------------------------------------- list criteria ------------------------------------------------ #

def test_add_criteria_prepends_a_match_stage_to_a_pipeline() -> None:
    """The server's $match runs before any client stage, so no $project can defeat it."""
    client_stages = [{'$lookup': {'from': 'framework.categories'}}, {'$match': {'x': 1}}]
    params = _params(list(client_stages))

    params.add_criteria(CONDITION)

    assert params.get_criteria() == [{'$match': CONDITION}, *client_stages]


def test_add_criteria_prepends_to_an_empty_pipeline() -> None:
    """An empty pipeline gains exactly one stage."""
    params = _params([])

    params.add_criteria(CONDITION)

    assert params.get_criteria() == [{'$match': CONDITION}]


def test_add_criteria_does_not_mutate_the_pipeline_it_was_given() -> None:
    """The client's stage list is rebuilt, not appended to - it is echoed back in the response."""
    client_stages = [{'$match': {'x': 1}}]
    params = _params(client_stages)

    params.add_criteria(CONDITION)

    assert client_stages == [{'$match': {'x': 1}}]


def test_add_criteria_twice_keeps_both_conditions_in_order() -> None:
    """Two server conditions both land, the later one first."""
    params = _params([])

    params.add_criteria(CONDITION)
    params.add_criteria({'active': True})

    assert params.get_criteria() == [{'$match': {'active': True}}, {'$match': CONDITION}]
