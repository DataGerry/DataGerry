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
Unit tests for access_rules.assignment_scope_rules and the scope catalogue (phase 9, R29, R30)

Pinned: '*' needs nothing; a malformed scope answers its shape problems; a list is resolved against the role's Types
and cast - the stored scope cast and canonical, every problem named; the role's Types read by id (every Type for '*');
the catalogue answers from the code
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_rules.assignment_scope_rules import judge_scope, role_type_documents
from cmdb.framework.scope_compiler import KIND_OPERATORS, MAX_SCOPE_BLOCKS, ScopeMessage
from cmdb.framework.scope_compiler.scope_catalogue import scope_catalogue
# -------------------------------------------------------------------------------------------------------------------- #

TYPES: list[dict[str, Any]] = [{'public_id': 1, 'fields': [{'name': 'size', 'type': 'number'}],
                                'render_meta': {'sections': []}}]


@pytest.mark.parametrize('scope, expected', [
    ('*', ('*', [])),
    ('nope', ('nope', [ScopeMessage.NOT_A_LIST.value])),
    ([{'op': 'in', 'value': ['3', 1], 'field': 'size'}],
     ([{'field': 'size', 'op': 'in', 'value': [1, 3]}], [])),
    ([{'field': 'gone', 'op': 'exists'}], ([{'field': 'gone', 'op': 'exists'}],
                                           [ScopeMessage.NO_CARRIER.value.format(field='gone')])),
], ids=['every-object', 'not-a-list', 'cast-and-canonical', 'no-carrier'])
def test_judge_scope(scope: Any, expected: tuple[Any, list[str]]) -> None:
    """The stored scope, and the problems"""
    assert judge_scope(scope, TYPES) == expected


@pytest.mark.parametrize('types, criteria', [('*', {}), ([3, 1], {'public_id': {'$in': [3, 1]}})],
                         ids=['every-type', 'listed'])
def test_role_type_documents(types: Any, criteria: dict[str, Any]) -> None:
    """One projected read"""
    manager = MagicMock()

    role_type_documents({'types': types}, manager)

    assert manager.find.call_args.kwargs['criteria'] == criteria


def test_the_catalogue_answers_from_the_code() -> None:
    """Operators per kind, caps"""
    catalogue = scope_catalogue()

    assert set(catalogue['kind_operators']) == set(KIND_OPERATORS)
    assert catalogue['limits']['conditions'] == MAX_SCOPE_BLOCKS
    assert catalogue['blocks'] == ['within', 'in_network', 'related_to'] and catalogue['related_to_filter'] == 'relation'
    assert catalogue['tokens'] == ['person', 'groups']
