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
Unit tests for field classes in the access decision (phase 12) - pure: grants built from documents

Pinned: a role's ``field_classes`` reach its grant entries; on a restricted Type a regular field needs
``write_regular_fields``, a classed field a role listing its class (unconditional or matching the state), a ``system``
field is refused always - on an open Type too, where every other field stays writable (D1, D2); the decision names the
refused fields at the FIELD_CLASS step; ``classes_of_fields`` reads the classed fields of a definition list
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_engine import (
    AccessDecisionStep,
    AccessGrants,
    build_grants,
    classes_of_fields,
    decide,
    refused_fields,
)
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

SERVER, OPEN = 11, 12
GROUP: int = 21
EDIT, CREATE = ScopeOperation.EDIT, ScopeOperation.CREATE
CLASSES: dict[str, str] = {'iso': 'compliance', 'iso_at': 'system'}


def _grants(regular: bool, classes: list[str], scope: Any = '*') -> AccessGrants:
    """One assignment of the user's group on the server Type"""
    return build_grants([{'public_id': 1, 'group_id': GROUP, 'role_id': 31, 'scope': scope}],
                        [{'public_id': 31, 'types': [SERVER], 'operations': ['view', 'create', 'edit'],
                          'write_regular_fields': regular, 'field_classes': classes}], [GROUP])


def _object(type_id: int = SERVER, **values: Any) -> dict[str, Any]:
    """An object with the given field values"""
    return {'public_id': 5, 'type_id': type_id, 'fields': [{'name': name, 'value': value}
                                                         for name, value in values.items()]}


def test_the_entries_carry_the_role_s_classes() -> None:
    """Names only, as a frozenset"""
    grants = _grants(True, ['compliance', 3])

    assert grants.entries[0].field_classes == frozenset({'compliance'})
    assert grants.writes_class(EDIT, SERVER, 'compliance') and not grants.writes_class(EDIT, SERVER, 'other')
    assert not grants.writes_class(ScopeOperation.DELETE, SERVER, 'compliance')


@pytest.mark.parametrize('regular, classes, refused', [
    (True, [], ('iso', 'iso_at')),
    (True, ['compliance'], ('iso_at',)),
    (False, ['compliance'], ('host', 'iso_at')),
    (False, [], ('host', 'iso', 'iso_at')),
], ids=['operator', 'admin', 'auditor', 'nothing'])
def test_each_field_by_its_class(regular: bool, classes: list[str], refused: tuple[str, ...]) -> None:
    """Regular by write_regular_fields, classed by the class, system never"""
    assert refused_fields(_grants(regular, classes), EDIT, SERVER, ['host', 'iso', 'iso_at'], (), CLASSES) == refused


def test_on_an_open_type_only_the_system_field_is_refused() -> None:
    """D1 + D2"""
    assert refused_fields(_grants(False, []), EDIT, OPEN, ['host', 'iso', 'iso_at'], (), CLASSES) == ('iso_at',)


def test_without_classes_every_field_is_regular() -> None:
    """The phase 5 behaviour"""
    assert refused_fields(_grants(True, []), EDIT, SERVER, ['iso'], ()) == ()


def test_a_matching_conditional_assignment_writes_its_classes() -> None:
    """Its role counts like an unconditional one"""
    grants = _grants(False, ['compliance'], scope=[{'field': 'host', 'op': 'exists'}])
    matching = (MagicMock(entry=grants.entries[0]),)

    assert refused_fields(grants, EDIT, SERVER, ['host', 'iso'], matching, CLASSES) == ('host',)


def test_the_decision_names_the_refused_fields() -> None:
    """FIELD_CLASS step; only changed fields count"""
    grants = _grants(True, [])
    decision = decide(grants, EDIT, _object(host='a', iso=False), _object(host='b', iso=True), field_classes=CLASSES)
    unchanged = decide(grants, EDIT, _object(host='a', iso=False), _object(host='b', iso=False),
                       field_classes=CLASSES)

    assert (decision.allowed, decision.step, decision.refused_fields) == (False, AccessDecisionStep.FIELD_CLASS,
                                                                          ('iso',))
    assert unchanged.allowed


def test_a_create_counts_every_filled_field() -> None:
    """An empty value is no write"""
    grants = _grants(True, [])

    assert not decide(grants, CREATE, None, _object(host='a', iso=True), field_classes=CLASSES).allowed
    assert decide(grants, CREATE, None, _object(host='a', iso=None), field_classes=CLASSES).allowed


def test_classes_of_fields() -> None:
    """Only a non-empty class name counts"""
    fields = [{'name': 'a', 'protection': 'x'}, {'name': 'b', 'protection': ''}, {'name': 'c'},
              {'name': 'd', 'protection': None}, 'junk', {'protection': 'y'}]

    assert classes_of_fields(fields) == {'a': 'x'}
