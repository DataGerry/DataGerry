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
Unit tests for conditional assignments in the access engine (phase 9 step 8, R21-R28) - pure: grants built from
documents, the evaluation built by ``build_scope_evaluation``

Pinned: a conditional assignment restricts its Types, never counts in ``granted`` (Type-level answers stay fail
closed), but counts in ``reachable`` / ``may``; a malformed scope grants nothing; ``decide`` allows a Type held only
conditionally on a state the condition matches - judging every state (an edit may neither leave nor enter the scope),
field writing per matching assignment, the trace naming it; an entry whose fields no longer resolve grants nothing; a
location or network condition judges each state by the scope block computed for it, never by one it carries (phase 10)
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_engine import (
    AccessDecisionStep,
    AccessGrants,
    ScopeEvaluation,
    build_grants,
    decide,
)
from cmdb.framework.access_engine.access_denial import denied_for
from cmdb.framework.access_engine.scope_evaluation import build_scope_evaluation, reads_scope_block
from cmdb.framework.scope_compiler import ScopeContext
from cmdb.models.access_model import ScopeOperation

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.scope_compiler import ScopeResolutionError
# -------------------------------------------------------------------------------------------------------------------- #

SERVER: int = 11
ROUTER: int = 12
GROUP: int = 21
SITE: int = 41
SITE_NODE: int = 51
OTHER_NODE: int = 52
NOW: datetime = datetime(2026, 11, 25, tzinfo=timezone.utc)
VIEW, CREATE, EDIT, DELETE = ScopeOperation.VIEW, ScopeOperation.CREATE, ScopeOperation.EDIT, ScopeOperation.DELETE
SCOPE: list[dict[str, Any]] = [{'field': 'site', 'op': 'equals', 'value': 'fulda'}]
TYPE_DOCUMENTS: list[dict[str, Any]] = [{'public_id': SERVER, 'fields': [{'name': 'site', 'type': 'text'}],
                                         'render_meta': {'sections': []}}]


def _role(public_id: int, types: Any, operations: list[str], writes: bool = True) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'types': types, 'operations': operations, 'write_regular_fields': writes}


def _assignment(public_id: int, role_id: int, scope: Any) -> dict[str, Any]:
    """A stored assignment of the user's group"""
    return {'public_id': public_id, 'group_id': GROUP, 'role_id': role_id, 'scope': scope}


def _grants(scope: Any = None, writes: bool = True) -> AccessGrants:
    """View / edit / create on servers where the site is fulda; full view on routers"""
    return build_grants([_assignment(1, 31, SCOPE if scope is None else scope), _assignment(2, 32, '*')],
                        [_role(31, [SERVER], ['view', 'edit', 'create'], writes), _role(32, [ROUTER], ['view'])],
                        [GROUP])


def _object(site: Any, type_id: int = SERVER, **extra: Any) -> dict[str, Any]:
    """A server in a site"""
    return {'public_id': 5, 'type_id': type_id, 'fields': [{'name': 'site', 'value': site}, *extra.get('more', [])]}


def _evaluation(grants: AccessGrants, documents: list[dict[str, Any]] | None = None) -> ScopeEvaluation:
    """The grants' conditional entries compiled"""
    entries = tuple(entry for entry in grants.entries if entry.conditional)

    return build_scope_evaluation(entries, TYPE_DOCUMENTS if documents is None else documents, ScopeContext(), NOW)


class TestGrants:
    """build_grants with a conditional assignment"""

    def test_it_restricts_but_grants_only_reachably(self) -> None:
        """Not in granted - every Type-level answer stays closed; in reachable / may"""
        grants = _grants()

        assert grants.is_restricted(SERVER)
        assert not grants.allows(VIEW, SERVER) and grants.may(VIEW, SERVER)
        assert not grants.may(DELETE, SERVER)
        assert denied_for(grants, VIEW).denies(SERVER) and not denied_for(grants, VIEW, reachable=True).denies(SERVER)
        assert [entry.assignment_id for entry in grants.conditional_entries(VIEW, SERVER)] == [1]
        assert grants.granting_assignment_ids(VIEW, SERVER) == []

    def test_a_malformed_scope_grants_nothing(self) -> None:
        """Neither in full nor conditionally - it still restricts"""
        grants = _grants(scope=[{'field': 'site'}])

        assert grants.is_restricted(SERVER) and not grants.may(VIEW, SERVER)
        assert [entry.assignment_id for entry in grants.entries] == [2]


class TestDecide:
    """Objects of a Type held only conditionally"""

    @pytest.mark.parametrize('operation, before, after, allowed', [
        (VIEW, _object('fulda'), None, True),
        (VIEW, _object('kassel'), None, False),
        (VIEW, _object(None), None, False),
        (CREATE, None, _object('fulda'), True),
        (CREATE, None, _object('kassel'), False),
        (EDIT, _object('fulda'), _object('fulda'), True),
        (EDIT, _object('fulda'), _object('kassel'), False),
        (EDIT, _object('kassel'), _object('fulda'), False),
        (DELETE, _object('fulda'), None, False),
    ], ids=['view-in', 'view-out', 'view-empty', 'create-in', 'create-out', 'edit-in', 'edit-out-of-scope',
            'edit-into-scope', 'delete-not-granted'])
    def test_every_judged_state_must_match(self, operation: ScopeOperation, before: Any, after: Any,
                                           allowed: bool) -> None:
        """Nobody moves an object out of their scope or into it from outside"""
        grants = _grants()

        assert decide(grants, operation, before, after, evaluation=_evaluation(grants)).allowed is allowed

    @pytest.mark.parametrize('operation, before, after, allowed', [
        (CREATE, None, {'public_id': 5, 'type_id': SERVER, 'placed_in': SITE_NODE}, True),
        (CREATE, None, {'public_id': 5, 'type_id': SERVER, 'placed_in': OTHER_NODE}, False),
        (EDIT, {'public_id': 5, 'type_id': SERVER, 'placed_in': SITE_NODE},
         {'public_id': 5, 'type_id': SERVER, 'placed_in': OTHER_NODE}, False),
        (EDIT, {'public_id': 5, 'type_id': SERVER, 'placed_in': SITE_NODE},
         {'public_id': 5, 'type_id': SERVER, 'placed_in': SITE_NODE}, True),
    ], ids=['create-inside', 'create-outside', 'edit-moving-out', 'edit-staying'])
    def test_a_within_condition_judges_each_states_own_block(self, operation: ScopeOperation, before: Any,
                                                              after: Any, allowed: bool) -> None:
        """
        The block is computed for the judged state - a stored block it carries is ignored: the create of a new
        object inside passes, an edit moving one out does not (phase 10, B1 + B2)
        """
        grants = _grants(scope=[{'within': SITE}])
        entries = tuple(entry for entry in grants.entries if entry.conditional)
        blocks = MagicMock()
        blocks.block_of.side_effect = lambda state: {'locations': [SITE] if state['placed_in'] == SITE_NODE else [9]}
        stale = {'_scope': {'locations': [SITE]}}
        evaluation = build_scope_evaluation(entries, TYPE_DOCUMENTS, ScopeContext(), NOW, blocks)

        assert decide(grants, operation, before and {**before, **stale}, {**after, **stale},
                      evaluation=evaluation).allowed is allowed

    def test_a_block_that_cannot_be_read_is_the_resolution_error(self) -> None:
        """A 500 like a failed grants read"""
        grants = _grants(scope=[{'within': SITE}])
        blocks = MagicMock()
        blocks.block_of.side_effect = BaseManagerIterationError('down')
        evaluation = build_scope_evaluation(tuple(entry for entry in grants.entries if entry.conditional),
                                            TYPE_DOCUMENTS, ScopeContext(), NOW, blocks)

        with pytest.raises(ScopeResolutionError):
            evaluation.matching(VIEW, _object('fulda'))

    def test_no_location_or_network_condition_computes_no_block(self) -> None:
        """Nothing read for a field comparison"""
        assert not reads_scope_block(tuple(entry for entry in _grants().entries if entry.conditional))
        assert reads_scope_block(tuple(entry for entry in _grants(scope=[{'in_network': 3}]).entries
                                       if entry.conditional))

    def test_without_an_evaluation_a_conditional_type_is_refused(self) -> None:
        """Fail closed"""
        decision = decide(_grants(), VIEW, _object('fulda'))

        assert (decision.allowed, decision.step, decision.type_id) == (False, AccessDecisionStep.SCOPE, SERVER)

    def test_field_writing_is_judged_on_the_matching_assignment(self) -> None:
        """Its role writes no regular field - a changed field is refused"""
        grants = _grants(writes=False)
        decision = decide(grants, EDIT, _object('fulda'), _object('fulda', more=[{'name': 'x', 'value': 1}]),
                          evaluation=_evaluation(grants))

        assert (decision.allowed, decision.step, decision.refused_fields) == (
            False, AccessDecisionStep.FIELD_CLASS, ('x',))

    def test_a_trace_names_the_matching_assignment(self) -> None:
        """The conditional one"""
        grants = _grants()

        assert decide(grants, VIEW, _object('fulda'), trace=True, evaluation=_evaluation(grants)).assignment_ids == (1,)

    def test_a_full_grant_on_another_type_is_untouched(self) -> None:
        """Routers by the unconditional assignment"""
        grants = _grants()

        assert decide(grants, VIEW, _object(None, ROUTER), evaluation=_evaluation(grants)).allowed


def test_an_entry_whose_fields_no_longer_resolve_grants_nothing() -> None:
    """The role's Types carry no 'site' any more - the entry is left out"""
    grants = _grants()
    evaluation = _evaluation(grants, [{'public_id': SERVER, 'fields': [], 'render_meta': {'sections': []}}])

    assert not evaluation.grants
    assert not decide(grants, VIEW, _object('fulda'), evaluation=evaluation).allowed
