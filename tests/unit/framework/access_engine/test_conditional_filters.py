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
Unit tests for the object-level filters with conditional assignments (phase 9 step 8, R21, R23, R25, R26) - the grants
and the evaluation stood in

Pinned: ``scope_filter`` adds one clause per conditional assignment (its Types AND its compiled scope) beside the full
grants, an ``$and`` for several operations, the clause alone for one Type; nothing conditional is the Type-only filter
as before; ``record_scope_filter`` never adds a condition (history and other collections, fail closed); the Type list
(``permitted_types_criteria``), ``type_reachable`` and ``operations_on_types`` count a conditional grant (R23), the
Type-level ``type_allows`` / ``denied_type_ids`` do not (R25); ``object_operation_values`` judges the object
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.access_engine import access_filters
from cmdb.framework.access_engine import access_decision
from cmdb.framework.access_engine import (
    build_grants,
    object_operation_values,
    operations_on_types,
    permitted_types_criteria,
    record_scope_filter,
    scope_filter,
    type_allows,
    type_reachable,
)
from cmdb.framework.access_engine.scope_evaluation import build_scope_evaluation
from cmdb.framework.scope_compiler import ScopeContext
from cmdb.models.access_model import ScopeOperation
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SERVER: int = 11
ROUTER: int = 12
GROUP: int = 21
USER: CmdbUser = CmdbUser(public_id=1, user_name='conditional', active=True, group_ids=[GROUP])
NOW: datetime = datetime(2026, 11, 25, tzinfo=timezone.utc)
VIEW, EDIT = ScopeOperation.VIEW, ScopeOperation.EDIT
SITE_IS_FULDA: dict[str, Any] = {'fields': {'$elemMatch': {'name': 'site', 'value': {'$eq': 'fulda'}}}}


@pytest.fixture(autouse=True)
def fixture_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """View + edit on servers where the site is fulda; routers restricted to another group"""
    grants = build_grants(
        [{'public_id': 1, 'group_id': GROUP, 'role_id': 31,
          'scope': [{'field': 'site', 'op': 'equals', 'value': 'fulda'}]}],
        [{'public_id': 31, 'types': [SERVER], 'operations': ['view', 'edit']},
         {'public_id': 32, 'types': [ROUTER], 'operations': ['view']}],
        [GROUP])
    evaluation = build_scope_evaluation(
        tuple(entry for entry in grants.entries if entry.conditional),
        [{'public_id': SERVER, 'fields': [{'name': 'site', 'type': 'text'}], 'render_meta': {'sections': []}}],
        ScopeContext(), NOW)

    for module in (access_filters, access_decision):
        monkeypatch.setattr(module, 'load_grants', lambda _user: grants)
        monkeypatch.setattr(module, 'load_scope_evaluation', lambda _user, _grants: evaluation)


class TestScopeFilter:
    """Lists of objects"""

    def test_the_full_grants_or_the_condition_on_its_types(self) -> None:
        """Servers and routers restricted, servers granted where the site is fulda"""
        assert scope_filter(USER, VIEW) == {'$or': [
            {'type_id': {'$nin': [SERVER, ROUTER]}},
            {'$and': [{'type_id': {'$in': [SERVER]}}, {'$and': [SITE_IS_FULDA]}]},
        ]}

    def test_one_type_is_the_condition_alone(self) -> None:
        """No type clause needed"""
        assert scope_filter(USER, VIEW, SERVER) == {'$or': [{'type_id': {'$in': []}}, {'$and': [SITE_IS_FULDA]}]}

    def test_several_operations_must_all_hold(self) -> None:
        """An $and of the per-operation filters"""
        assert scope_filter(USER, [VIEW, EDIT]) == {'$and': [scope_filter(USER, VIEW), scope_filter(USER, EDIT)]}

    def test_an_operation_no_condition_grants_is_type_only(self) -> None:
        """Delete: nothing conditional - as before"""
        assert scope_filter(USER, ScopeOperation.DELETE) == {'type_id': {'$nin': [SERVER, ROUTER]}}

    def test_records_never_take_a_condition(self) -> None:
        """History: a Type held only conditionally is denied"""
        assert record_scope_filter(USER, VIEW) == {'type_id': {'$nin': [SERVER, ROUTER]}}


class TestTypeAnswers:
    """Some objects (R23) versus every object (R25)"""

    def test_the_reachable_answers_count_the_condition(self) -> None:
        """Type list, single Type, operations"""
        assert permitted_types_criteria(USER, VIEW) == {'public_id': {'$nin': [ROUTER]}}
        assert type_reachable(USER, VIEW, SERVER) and not type_reachable(USER, VIEW, ROUTER)
        assert operations_on_types(USER, [SERVER])[SERVER] == [VIEW, EDIT]

    def test_the_type_level_gates_stay_closed(self) -> None:
        """Fail closed"""
        assert not type_allows(USER, VIEW, SERVER)


@pytest.mark.parametrize('site, expected', [('fulda', ['view', 'edit']), ('kassel', [])],
                         ids=['in-scope', 'out-of-scope'])
def test_object_operation_values_judge_the_object(site: str, expected: list[str]) -> None:
    """Create counts only when reachable - not granted here"""
    document = {'public_id': 5, 'type_id': SERVER, 'fields': [{'name': 'site', 'value': site}]}

    assert object_operation_values(USER, document) == expected
