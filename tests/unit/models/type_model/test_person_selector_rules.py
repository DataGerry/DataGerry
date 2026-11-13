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
Unit tests for cmdb.models.type_model.person_selector_rules and the structure rule built on it

Pure tests. Pinned:

  - a person selector is a dict declaring ``type: person``; its settings read as stored, a missing or broken one as
    nothing selectable / not multiple
  - a definition selects PERSON and / or PERSON_GROUP, each once, at least one; says ``multiple`` as a boolean; and
    carries no default - each broken setting is its own message naming the field
  - the type structure rule reports every broken selector of a type together, and passes a sound one
  - which selectors store one id and which a list, and when an update changes that shape
"""
from typing import Any

import pytest

from cmdb.models.type_model.type_constants import PersonSelectorError, STRUCTURE_ERROR_SEPARATOR
from cmdb.models.type_model.type_structure_rules import STRUCTURE_RULES, validate_type_structure
from cmdb.models.type_model.person_selector_rules import (
    SELECTABLE_KINDS,
    is_multiple,
    is_person_selector,
    person_selector_problems,
    person_value_shape_changed,
    person_value_shapes,
    selectable_kinds,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

NAME: str = 'owner'
ALLOWED: list[str] = ['PERSON', 'PERSON_GROUP']


def _selector(name: str = NAME, selectable: Any = None, multiple: Any = False, **extra: Any) -> dict[str, Any]:
    """A person selector definition"""
    return {'type': 'person', 'name': name, 'label': name.title(),
            'selectable': ['PERSON'] if selectable is None else selectable, 'multiple': multiple, **extra}


def _type(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A type document showing every field in one section"""
    return {'name': 'owned', 'fields': fields, 'render_meta': {'sections': [
        {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [field['name'] for field in fields]},
    ]}}


def test_the_selectable_kinds() -> None:
    """The two markers whose objects a selector may select"""
    assert SELECTABLE_KINDS == (SpecialType.PERSON, SpecialType.PERSON_GROUP)


@pytest.mark.parametrize('field, expected', [
    (_selector(), True), ({'type': 'ref', 'name': NAME}, False), ({'name': NAME}, False), ('person', False),
], ids=['selector', 'reference', 'no-kind', 'not-a-dict'])
def test_is_person_selector(field: Any, expected: bool) -> None:
    """Only a dict declaring the kind"""
    assert is_person_selector(field) is expected


@pytest.mark.parametrize('selectable, expected', [
    (['PERSON_GROUP', 'PERSON'], ['PERSON_GROUP', 'PERSON']), ('PERSON', []), (None, []), (['PERSON', 3], ['PERSON']),
], ids=['as-listed', 'not-a-list', 'missing', 'non-strings-dropped'])
def test_selectable_kinds_reads_as_stored(selectable: Any, expected: list[str]) -> None:
    """In the stored order; a broken setting selects nothing"""
    field: dict[str, Any] = {'type': 'person', 'name': NAME}

    if selectable is not None:
        field['selectable'] = selectable

    assert selectable_kinds(field) == expected


@pytest.mark.parametrize('multiple, expected', [(True, True), (False, False), ('true', False), (None, False)],
                         ids=['true', 'false', 'text', 'missing'])
def test_is_multiple_only_for_true(multiple: Any, expected: bool) -> None:
    """Anything but the boolean true holds one object"""
    assert is_multiple({'multiple': multiple}) is expected


@pytest.mark.parametrize('selectable', [['PERSON'], ['PERSON_GROUP'], ['PERSON', 'PERSON_GROUP']], ids=str)
@pytest.mark.parametrize('multiple', [True, False], ids=['several', 'one'])
def test_a_sound_definition_has_no_problems(selectable: list[str], multiple: bool) -> None:
    """Every combination of the settings"""
    assert person_selector_problems(_selector(selectable=selectable, multiple=multiple)) == []


@pytest.mark.parametrize('selectable', [[], ['RACK'], ['PERSON', 'PERSON'], 'PERSON', [None]],
                         ids=['empty', 'not-a-person-kind', 'repeated', 'not-a-list', 'null'])
def test_a_broken_selectable_is_named(selectable: Any) -> None:
    """With what is allowed"""
    assert person_selector_problems(_selector(selectable=selectable)) == [
        PersonSelectorError.SELECTABLE.format(name=NAME, allowed=ALLOWED),
    ]


@pytest.mark.parametrize('multiple', [None, 'true', 1], ids=['missing', 'text', 'number'])
def test_a_broken_multiple_is_named(multiple: Any) -> None:
    """A boolean, nothing else"""
    assert person_selector_problems(_selector(multiple=multiple)) == [PersonSelectorError.MULTIPLE.format(name=NAME)]


@pytest.mark.parametrize('default', [7, [7], 'someone'], ids=['id', 'ids', 'text'])
def test_a_default_is_refused(default: Any) -> None:
    """A default would be an object id no type can know in advance"""
    assert person_selector_problems(_selector(value=default)) == [PersonSelectorError.DEFAULT.format(name=NAME)]


@pytest.mark.parametrize('empty', [None, '', []], ids=['none', 'empty-text', 'empty-list'])
def test_an_empty_default_is_no_default(empty: Any) -> None:
    """What the type builder sends for a field without one"""
    assert person_selector_problems(_selector(value=empty)) == []


def test_the_structure_rule_reports_every_broken_selector_together() -> None:
    """Every finding of one document, in field order; a sound selector passes"""
    fields = [_selector('sound'), _selector('no-kinds', selectable=[]), _selector('no-multiple', multiple=None)]

    assert validate_type_structure(_type(fields)) == STRUCTURE_ERROR_SEPARATOR.join([
        PersonSelectorError.SELECTABLE.format(name='no-kinds', allowed=ALLOWED),
        PersonSelectorError.MULTIPLE.format(name='no-multiple'),
    ])
    assert '_person_selector_errors' in {rule.__name__ for rule in STRUCTURE_RULES}


def test_a_type_of_sound_selectors_passes() -> None:
    """In a plain section"""
    assert validate_type_structure(_type([_selector('one'), _selector('several', multiple=True)])) is None


def test_person_value_shapes_splits_by_multiple() -> None:
    """Other kinds are not counted"""
    fields = [_selector('one'), _selector('several', multiple=True), {'type': 'text', 'name': 'note'}]

    assert person_value_shapes(fields) == (['one'], ['several'])


@pytest.mark.parametrize('old, new, expected', [
    ([_selector()], [_selector()], False),
    ([_selector()], [_selector(multiple=True)], True),
    ([_selector(multiple=True)], [_selector()], True),
    ([], [_selector()], True),
    ([{'type': 'text', 'name': NAME}], [_selector()], True),
    ([_selector()], [_selector(selectable=ALLOWED)], False),
    ([_selector()], [], False),
], ids=['unchanged', 'to-several', 'to-one', 'added', 'retyped', 'kinds-only', 'removed'])
def test_person_value_shape_changed(old: list[dict[str, Any]], new: list[dict[str, Any]], expected: bool) -> None:
    """Only an added or retyped selector, or one switching between one and several, changes the stored shape"""
    assert person_value_shape_changed(old, new) is expected
