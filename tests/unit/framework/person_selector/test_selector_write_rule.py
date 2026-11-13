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
Unit tests for cmdb.framework.person_selector.selector_write_rule

The managers are stubs over a small in-memory set of objects and types. Pinned:

  - a type without selectors reads nothing; a wrong shape is a 400 before any read
  - only the ids a write introduces are judged: unknown (400), then unreadable (403), then of a kind the selector does
    not select (400) - an id already stored passes, whatever it names now
  - an update keeps the stored ids the writer may not read: appended to a list, kept for a single selector sent empty
  - nothing is read when nothing is introduced and the writer is denied nothing
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.person_selector.person_selector_constants import PersonSelectorWriteError
from cmdb.framework.person_selector.selector_write_rule import SelectorRefusal, check_person_selector_values
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 31
GROUP_TYPE: int = 32
HIDDEN_PERSON_TYPE: int = 33
RACK_TYPE: int = 34
PERSON: int = 101
GROUP: int = 102
HIDDEN_PERSON: int = 103
RACK: int = 104
OBJECTS: dict[int, int] = {PERSON: PERSON_TYPE, GROUP: GROUP_TYPE, HIDDEN_PERSON: HIDDEN_PERSON_TYPE, RACK: RACK_TYPE}
MARKERS: dict[int, str] = {PERSON_TYPE: 'PERSON', GROUP_TYPE: 'PERSON_GROUP', HIDDEN_PERSON_TYPE: 'PERSON',
                           RACK_TYPE: 'RACK'}

ONE: str = 'owner'
SEVERAL: str = 'members'


def _managers() -> tuple[MagicMock, MagicMock]:
    """Stub managers answering the projected reads from OBJECTS and MARKERS"""
    objects, types = MagicMock(), MagicMock()
    objects.find.side_effect = lambda criteria, **_kwargs: [
        {'public_id': object_id, 'type_id': OBJECTS[object_id]}
        for object_id in criteria['public_id']['$in'] if object_id in OBJECTS
    ]
    types.find.side_effect = lambda criteria, **_kwargs: [
        {'public_id': type_id, 'special_type': MARKERS[type_id]} for type_id in criteria['public_id']['$in']
    ]

    return objects, types


def _type(one_kinds: list[str] | None = None) -> Any:
    """A type with a single selector (persons by default) and a multiple one (persons and groups)"""
    return SimpleNamespace(fields=[
        {'type': 'person', 'name': ONE, 'selectable': one_kinds or ['PERSON'], 'multiple': False},
        {'type': 'person', 'name': SEVERAL, 'selectable': ['PERSON', 'PERSON_GROUP'], 'multiple': True},
    ])


def _object(one: Any = None, several: Any = None) -> dict[str, Any]:
    """A document holding both selectors"""
    return {'fields': [{'name': ONE, 'value': one}, {'name': SEVERAL, 'value': several}]}


def _check(candidate: dict[str, Any], previous: dict[str, Any] | None = None, hidden: frozenset[int] = frozenset(),
           object_type: Any = None) -> tuple[SelectorRefusal | None, MagicMock, MagicMock]:
    """Runs the rule with stub managers; the writer is denied the given types"""
    objects, types = _managers()
    refusal = check_person_selector_values(objects, types, lambda: hidden, candidate, (object_type or _type()).fields,
                                           previous)

    return refusal, objects, types


def test_a_type_without_selectors_reads_nothing() -> None:
    """And refuses nothing"""
    refusal, objects, _ = _check(_object('junk'), object_type=SimpleNamespace(fields=[{'type': 'text', 'name': 'x'}]))

    assert refusal is None
    objects.find.assert_not_called()


def test_a_wrong_shape_is_a_400_before_any_read() -> None:
    """Named"""
    refusal, objects, _ = _check(_object([PERSON], []))

    assert refusal == SelectorRefusal(HTTPStatus.BAD_REQUEST, PersonSelectorWriteError.SHAPE_SINGLE.format(name=ONE))
    objects.find.assert_not_called()


def test_sound_selections_pass() -> None:
    """A person in the single one, a person and a group in the multiple one"""
    assert _check(_object(PERSON, [PERSON, GROUP]))[0] is None


def test_an_unknown_id_is_a_400() -> None:
    """Naming the selector and the id"""
    assert _check(_object(None, [PERSON, 999]))[0] == SelectorRefusal(
        HTTPStatus.BAD_REQUEST, PersonSelectorWriteError.UNKNOWN.format(name=SEVERAL, ids=[999]))


def test_an_unreadable_object_is_a_403() -> None:
    """Before its kind is judged"""
    refusal, _, types = _check(_object(HIDDEN_PERSON, []), hidden=frozenset({HIDDEN_PERSON_TYPE}))

    assert refusal == SelectorRefusal(HTTPStatus.FORBIDDEN,
                                      PersonSelectorWriteError.NOT_READABLE.format(name=ONE, ids=[HIDDEN_PERSON]))
    types.find.assert_not_called()


@pytest.mark.parametrize('one, refused', [(GROUP, [GROUP]), (RACK, [RACK])], ids=['a-group', 'not-a-person-kind'])
def test_a_kind_the_selector_does_not_select_is_a_400(one: int, refused: list[int]) -> None:
    """The single selector selects persons only"""
    assert _check(_object(one, []))[0] == SelectorRefusal(
        HTTPStatus.BAD_REQUEST,
        PersonSelectorWriteError.NOT_SELECTABLE.format(name=ONE, kinds=['PERSON'], ids=refused))


def test_an_id_already_stored_is_not_judged_again() -> None:
    """Even one naming an object of a kind the selector no longer selects"""
    stored = _object(RACK, [])
    refusal, objects, _ = _check(_object(RACK, []), previous=stored)

    assert refusal is None
    objects.find.assert_not_called()


def test_an_update_keeps_the_stored_ids_the_writer_may_not_read() -> None:
    """Appended to the list it sent, kept in the single selector it sent empty"""
    stored = _object(HIDDEN_PERSON, [PERSON, HIDDEN_PERSON])
    candidate = _object(None, [GROUP])

    refusal, _, _ = _check(candidate, previous=stored, hidden=frozenset({HIDDEN_PERSON_TYPE}))

    assert refusal is None
    assert candidate['fields'][0]['value'] == HIDDEN_PERSON
    assert candidate['fields'][1]['value'] == [GROUP, HIDDEN_PERSON]


def test_a_readable_stored_id_left_out_is_removed() -> None:
    """Only what the writer cannot see is kept"""
    candidate = _object(None, [])

    assert _check(candidate, previous=_object(PERSON, [PERSON]), hidden=frozenset({HIDDEN_PERSON_TYPE}))[0] is None
    assert candidate['fields'] == [{'name': ONE, 'value': None}, {'name': SEVERAL, 'value': []}]
