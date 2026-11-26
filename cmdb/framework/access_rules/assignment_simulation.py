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
The assignment simulation (phase 11), pure: the one aggregation it runs and what its result says - no reads

A simulation counts the objects an assignment would reach, per Type, with ten samples, within the caller's own view
(D2); with a stored assignment the objects it would gain and lose (D4); with user tokens per member (D3). Its warnings
(D6) name conditions no index serves well, an empty scope, a scope matching every object of the role's Types, a token
resolving to nothing for a member, and the Types the assignment newly restricts. The reads live with the route
(``access_routes/assignment_simulation_helper``)
"""
from collections.abc import Iterable, Mapping
from typing import Any

from cmdb.utils import Builder
from cmdb.models.access_model import ALL_TYPES, ScopeRoleKey, UNCONDITIONAL_SCOPE
from cmdb.models.object_model import CmdbObjectKey
from cmdb.framework.scope_compiler import ScopeBlockKey, ScopeField, ScopeOperator
from cmdb.framework.access_rules.assignment_simulation_constants import (
    SAMPLE_LIMIT,
    SIMULATION_WARNING_MESSAGES,
    TEXT_KINDS,
    SimulationFacet,
    SimulationKey,
    SimulationWarning,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'all_of',
    'any_of',
    'role_clause',
    'simulation_pipeline',
    'member_facet',
    'facet_count',
    'facet_by_type',
    'facet_sample_ids',
    'simulation_warning',
    'condition_warnings',
    'count_warnings',
]

# The operators an index serves poorly: a negation, and an emptiness that also matches a missing entry
POORLY_INDEXED_OPERATORS: frozenset[str] = frozenset({ScopeOperator.NOT_EQUALS.value, ScopeOperator.NOT_IN.value,
                                                      ScopeOperator.IS_EMPTY.value})
# A filter no object matches
_NOTHING: dict[str, Any] = {CmdbObjectKey.TYPE_ID.value: {'$in': []}}
_COUNT: str = SimulationKey.COUNT.value


def all_of(*parts: dict[str, Any]) -> dict[str, Any]:
    """
    The filter matching what every part matches - an empty part matches everything and is left out

    Args:
        *parts (dict[str, Any]): Filters

    Returns:
        dict[str, Any]: One filter; empty when every part is
    """
    kept: list[dict[str, Any]] = [part for part in parts if part]

    if not kept:
        return {}

    return kept[0] if len(kept) == 1 else {'$and': kept}


def any_of(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    The filter matching what any part matches - an empty part matches everything, no part matches nothing

    Args:
        parts (list[dict[str, Any]]): Filters

    Returns:
        dict[str, Any]: One filter
    """
    if not parts:
        return dict(_NOTHING)

    if any(not part for part in parts):
        return {}

    return parts[0] if len(parts) == 1 else {'$or': parts}


def role_clause(role: Mapping[str, Any]) -> dict[str, Any]:
    """
    The objects of a scope role's Types

    Args:
        role (Mapping[str, Any]): The stored scope role

    Returns:
        dict[str, Any]: Empty for a role on every Type, else ``type_id $in`` its Types
    """
    types: Any = role.get(ScopeRoleKey.TYPES.value)

    if types == ALL_TYPES:
        return {}

    return {CmdbObjectKey.TYPE_ID.value: {'$in': sorted(types or [])}}


def member_facet(user_id: int) -> str:
    """
    The facet counting one member's reach

    Args:
        user_id (int): The member

    Returns:
        str: Its name
    """
    return f'{SimulationFacet.MEMBER_PREFIX.value}{user_id}'


def _count_facet(criteria: dict[str, Any]) -> list[dict[str, Any]]:
    """
    A facet counting what a filter matches

    Args:
        criteria (dict[str, Any]): The filter

    Returns:
        list[dict[str, Any]]: Its stages
    """
    return [Builder.match_(criteria), Builder.count_(_COUNT)]


def _sample_facet(criteria: dict[str, Any]) -> list[dict[str, Any]]:
    """
    A facet taking the first objects a filter matches, by id

    Args:
        criteria (dict[str, Any]): The filter

    Returns:
        list[dict[str, Any]]: Its stages
    """
    return [Builder.match_(criteria), Builder.sort_(CmdbObjectKey.PUBLIC_ID.value, 1), Builder.limit_(SAMPLE_LIMIT),
            Builder.project_({'_id': 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1})]


def simulation_pipeline(view: dict[str, Any], roles: list[dict[str, Any]], reach: dict[str, Any],
                        stored: dict[str, Any] | None, members: Mapping[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The one aggregation of a simulation: within the caller's view, the objects of the roles' Types, faceted

    Args:
        view (dict[str, Any]): The caller's own view filter (D2)
        roles (list[dict[str, Any]]): The role clauses - the simulated one first, the stored one beside it
        reach (dict[str, Any]): The objects the simulated assignment would reach
        stored (dict[str, Any] | None): The objects the stored assignment reaches - None for a create
        members (Mapping[int, dict[str, Any]]): Per member counted one by one, its reach (D3); empty without tokens

    Returns:
        list[dict[str, Any]]: The stages
    """
    facets: dict[str, list[dict[str, Any]]] = {
        SimulationFacet.BY_TYPE.value: [Builder.match_(reach), Builder.group_(
            f'${CmdbObjectKey.TYPE_ID.value}', {_COUNT: {'$sum': 1}})],
        SimulationFacet.SAMPLES.value: _sample_facet(reach),
        SimulationFacet.ROLE_TOTAL.value: _count_facet(roles[0]),
    }

    if stored is not None:
        gained: dict[str, Any] = all_of(reach, {'$nor': [stored]})
        lost: dict[str, Any] = all_of(stored, {'$nor': [reach]})
        facets[SimulationFacet.GAINED.value] = _count_facet(gained)
        facets[SimulationFacet.GAINED_SAMPLES.value] = _sample_facet(gained)
        facets[SimulationFacet.LOST.value] = _count_facet(lost)
        facets[SimulationFacet.LOST_SAMPLES.value] = _sample_facet(lost)

    for user_id, criteria in members.items():
        facets[member_facet(user_id)] = _count_facet(criteria)

    return [Builder.match_(all_of(view, any_of(roles))), Builder.facet_(facets)]


def facet_count(result: Mapping[str, Any], facet: str) -> int:
    """
    What a count facet counted

    Args:
        result (Mapping[str, Any]): The aggregation's one document
        facet (str): The facet

    Returns:
        int: The count; 0 when nothing matched (MongoDB answers no document then)
    """
    counted: list[dict[str, Any]] = result.get(facet) or []

    return counted[0][_COUNT] if counted else 0


def facet_by_type(result: Mapping[str, Any]) -> list[dict[str, int]]:
    """
    The count per Type

    Args:
        result (Mapping[str, Any]): The aggregation's one document

    Returns:
        list[dict[str, int]]: ``{type_id, count}`` ascending by Type
    """
    return sorted(({SimulationKey.TYPE_ID.value: row['_id'], _COUNT: row[_COUNT]}
                   for row in result.get(SimulationFacet.BY_TYPE.value) or []),
                  key=lambda row: row[SimulationKey.TYPE_ID.value])


def facet_sample_ids(result: Mapping[str, Any], facet: str) -> list[dict[str, int]]:
    """
    The samples of a sample facet

    Args:
        result (Mapping[str, Any]): The aggregation's one document
        facet (str): The facet

    Returns:
        list[dict[str, int]]: ``{public_id, type_id}``, ascending by id
    """
    return [dict(row) for row in result.get(facet) or []]


def simulation_warning(code: SimulationWarning, **values: Any) -> dict[str, str]:
    """
    One warning of the answer

    Args:
        code (SimulationWarning): What it warns about
        **values (Any): What its message names

    Returns:
        dict[str, str]: ``{code, message}``
    """
    return {SimulationKey.CODE.value: code.value,
            SimulationKey.MESSAGE.value: SIMULATION_WARNING_MESSAGES[code].format(**values)}


def condition_warnings(scope: Any, fields: Mapping[str, ScopeField]) -> list[dict[str, str]]:
    """
    The warnings a scope's conditions earn by themselves: a substring on a text, a negation or emptiness

    Args:
        scope (Any): The cast scope
        fields (Mapping[str, ScopeField]): Its fields, resolved across the role's Types

    Returns:
        list[dict[str, str]]: The warnings, each naming its fields
    """
    if scope == UNCONDITIONAL_SCOPE:
        return []

    contains: list[str] = []
    poorly: list[str] = []

    for block in scope:
        name: Any = block.get(ScopeBlockKey.FIELD.value)
        operator: Any = block.get(ScopeBlockKey.OP.value)

        if name is None:
            continue

        if operator == ScopeOperator.CONTAINS.value and name in fields and fields[name].kind in TEXT_KINDS:
            contains.append(name)
        elif operator in POORLY_INDEXED_OPERATORS:
            poorly.append(name)

    warnings: list[dict[str, str]] = []

    if contains:
        warnings.append(simulation_warning(SimulationWarning.UNINDEXED_CONTAINS, fields=sorted(set(contains))))

    if poorly:
        warnings.append(simulation_warning(SimulationWarning.POORLY_INDEXED, fields=sorted(set(poorly))))

    return warnings


def count_warnings(scope: Any, total: int, role_total: int, unresolved: Iterable[int],
                   newly_restricted: Iterable[int]) -> list[dict[str, str]]:
    """
    The warnings the counts earn

    Args:
        scope (Any): The cast scope
        total (int): The objects the assignment reaches (within the caller's view)
        role_total (int): The objects of the role's Types (within the caller's view)
        unresolved (Iterable[int]): The members a user token resolves to nothing for
        newly_restricted (Iterable[int]): The Types the assignment newly restricts

    Returns:
        list[dict[str, str]]: The warnings
    """
    warnings: list[dict[str, str]] = []

    if total == 0:
        warnings.append(simulation_warning(SimulationWarning.EMPTY))
    elif scope != UNCONDITIONAL_SCOPE and total == role_total:
        warnings.append(simulation_warning(SimulationWarning.EVERY_OBJECT))

    unresolved_ids: list[int] = sorted(unresolved)

    if unresolved_ids:
        warnings.append(simulation_warning(SimulationWarning.UNRESOLVED_TOKEN, user_ids=unresolved_ids))

    restricted: list[int] = sorted(newly_restricted)

    if restricted:
        warnings.append(simulation_warning(SimulationWarning.NEWLY_RESTRICTED, type_ids=restricted))

    return warnings
