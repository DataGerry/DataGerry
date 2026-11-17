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
Unit tests for cmdb.manager.objects_summary_helper

The summary line is what identifies an object everywhere it is not shown in full - lists, pickers,
references - so its text is a user-facing contract: `Type label #public_id - field | field`.

What these tests pin is mostly about ABSENCE, because that is where the line reads badly: a
summary field the object has no value for contributes neither text nor a separator (an unset field
once rendered the literal word 'None', and emitting the separator alone left the line trailing off),
while `0` and `False` are real data and are rendered. The separator therefore tracks the first field
actually emitted, not the first one configured.

Pure: no manager, no database - the object arrives as a document and its type as a stand-in.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.objects_summary_helper import (
    compose_summary_line,
    compose_summary_lines,
    label_person_values,
    summary_layout,
)
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
SECOND_OBJECT_ID: int = 701
OTHER_TYPE_ID: int = 51
OTHER_OBJECT_ID: int = 702
OWNER_PERSON_ID: int = 42
SECOND_PERSON_IDS: list[int] = [43, 44]
OWNER_PERSON_LABEL: str = 'Ada Lovelace'
SECOND_PERSON_LABELS: str = 'Grace Hopper, Ops team'
PERSON_FIELD: dict[str, Any] = {'name': 'owner', 'type': FieldType.PERSON.value}
HOSTNAME_FIELD: dict[str, Any] = {'name': 'hostname', 'type': FieldType.TEXT.value}


def _make_object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with the given public_id, type_id, and field list."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'fields': fields or [],
    }


def _make_type_mock(public_id: int, label: str, *, has_summaries: bool = False,
                    summary_fields: list[dict[str, Any]] | None = None) -> MagicMock:
    """Builds a MagicMock that quacks like a CmdbType for summary-line composition."""
    type_mock = MagicMock()
    type_mock.public_id = public_id
    type_mock.label = label
    type_mock.has_summaries.return_value = has_summaries

    summary_obj = MagicMock()
    summary_obj.fields = summary_fields or []
    type_mock.get_summary.return_value = summary_obj

    return type_mock


# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_summary_line_returns_default_prefix_when_type_has_no_summaries() -> None:
    """A type without summaries yields 'label #id' as the entire line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_line_omits_type_label_when_with_type_is_false() -> None:
    """with_type=False yields '#id' without the type label prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = compose_summary_line(obj_doc, type_mock, with_type=False)

    assert result == f"#{OWNER_OBJECT_ID}"


def test_compose_summary_line_appends_summary_fields_with_separators() -> None:
    """Type with summary fields appends '- first | second' to the default prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
        {'name': 'fqdn', 'value': 'web01.example.com'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'fqdn'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01 | web01.example.com"


@pytest.mark.parametrize('document', [
    {'public_id': OWNER_OBJECT_ID},
    {'public_id': OWNER_OBJECT_ID, 'fields': None},
    {'public_id': OWNER_OBJECT_ID, 'fields': ['not a row']},
    {'public_id': OWNER_OBJECT_ID, 'fields': [{'value': 'web01'}]},
], ids=['no-fields', 'fields-none', 'row-not-a-dict', 'row-without-name'])
def test_a_malformed_object_falls_back_to_the_default_prefix(document: dict[str, Any]) -> None:
    """One broken stored document must not fail a whole listing: it is shown by its prefix"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[{'name': 'hostname'}])

    assert compose_summary_line(document, type_mock) == f"Server #{OWNER_OBJECT_ID}"


def test_a_bug_while_reading_the_summary_propagates_as_itself() -> None:
    """Only a malformed object is caught; a programming error reaches the caller"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True)
    type_mock.get_summary.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError):
        compose_summary_line(_make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID), type_mock)


def test_the_first_row_of_a_name_wins() -> None:
    """A document listing a name twice shows the first value, as the line always has"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'first'}, {'name': 'hostname', 'value': 'second'},
    ])
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[{'name': 'hostname'}])

    assert compose_summary_line(obj_doc, type_mock) == f"Server #{OWNER_OBJECT_ID} - first"


def test_summary_layout_is_empty_without_a_summary() -> None:
    """A type configuring no summary has no summary fields, and its summary is not resolved"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    assert summary_layout(type_mock) == ([], set())
    type_mock.get_summary.assert_not_called()


def test_summary_layout_keeps_the_declaration_order_and_names_the_person_selectors() -> None:
    """The resolved summary field names in order, and the person selectors among them"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True,
                                summary_fields=[{'name': 'b'}, PERSON_FIELD, {'name': 'a'}])

    assert summary_layout(type_mock) == (['b', PERSON_FIELD['name'], 'a'], {PERSON_FIELD['name']})


def test_compose_summary_line_skips_a_summary_field_absent_from_the_object() -> None:
    """Regression: a summary field the object has no entry for must not render the text 'None'"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'missing'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01"


@pytest.mark.parametrize('unset_value', [None, ''], ids=['none', 'empty-string'])
def test_compose_summary_line_skips_an_unset_summary_value(unset_value) -> None:
    """Regression: an unset summary value must not leave the line trailing off as '#<id> - '"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': unset_value},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[{'name': 'hostname'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


@pytest.mark.parametrize('value, rendered', [(0, '0'), (False, 'False')], ids=['zero', 'false'])
def test_compose_summary_line_renders_falsy_but_present_values(value, rendered: str) -> None:
    """Only an absent value is skipped - a zero or a False is real data and must still show"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'ports', 'value': value},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[{'name': 'ports'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - {rendered}"


def test_compose_summary_line_separator_follows_the_first_emitted_field() -> None:
    """An unset FIRST field must not push a stray '|' to the front of the line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': None},
        {'name': 'fqdn', 'value': 'web01.example.com'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'fqdn'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01.example.com"


def test_compose_summary_line_closes_the_gap_left_by_an_unset_middle_field() -> None:
    """An unset field between two set ones leaves no double separator"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'a', 'value': 'x'},
        {'name': 'b', 'value': None},
        {'name': 'c', 'value': 'z'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'a'}, {'name': 'b'}, {'name': 'c'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - x | z"


def test_compose_summary_line_with_every_summary_field_unset_is_the_bare_prefix() -> None:
    """All summary fields unset yields the prefix alone, with no dangling separator"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'a', 'value': None},
        {'name': 'b', 'value': ''},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'a'}, {'name': 'b'}],
    )

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_lines_skips_what_has_no_line() -> None:
    """A document without an integer id, or whose type is not loaded, gets no line"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')
    docs = [
        _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID),
        {'public_id': 'drifted', 'type_id': OWNER_TYPE_ID, 'fields': []},
        _make_object_doc(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID + 1),
        {'public_id': OWNER_OBJECT_ID + 2, 'type_id': None, 'fields': []},
    ]

    assert compose_summary_lines(docs, {OWNER_TYPE_ID: type_mock}) == {OWNER_OBJECT_ID: f'Server #{OWNER_OBJECT_ID}'}


def test_compose_summary_lines_resolves_each_types_summary_once() -> None:
    """Two objects of one type ask that type for its summary once"""
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[{'name': 'hostname'}])
    docs = [_make_object_doc(public_id, OWNER_TYPE_ID, fields=[{'name': 'hostname', 'value': f'h{public_id}'}])
            for public_id in (OWNER_OBJECT_ID, OWNER_OBJECT_ID + 1)]

    lines = compose_summary_lines(docs, {OWNER_TYPE_ID: type_mock}, with_type=False)

    assert lines == {OWNER_OBJECT_ID: f'#{OWNER_OBJECT_ID} - h{OWNER_OBJECT_ID}',
                     OWNER_OBJECT_ID + 1: f'#{OWNER_OBJECT_ID + 1} - h{OWNER_OBJECT_ID + 1}'}
    type_mock.get_summary.assert_called_once()


# ---------------------------------------------- PERSON SELECTOR VALUES ---------------------------------------------- #

def _person_type() -> MagicMock:
    """A type whose summary is a text field and a person selector"""
    return _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[HOSTNAME_FIELD, PERSON_FIELD])


def _person_doc(public_id: int, hostname: str, owner: Any) -> dict[str, Any]:
    """An object of ``_person_type`` with the given host name and person selector value"""
    return _make_object_doc(public_id, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': hostname}, {'name': 'owner', 'value': owner},
    ])


def _labels(values: list[Any]) -> list[str]:
    """A labeller answering a fixed text per value, as the reader would see it"""
    texts: dict[Any, str] = {OWNER_PERSON_ID: OWNER_PERSON_LABEL, tuple(SECOND_PERSON_IDS): SECOND_PERSON_LABELS}

    return [texts.get(tuple(value) if isinstance(value, list) else value, '') for value in values]


def test_a_person_value_without_a_labeller_is_left_out_never_written_as_ids() -> None:
    """No labeller: the person value contributes neither its ids nor a separator"""
    line: str = compose_summary_line(_person_doc(OWNER_OBJECT_ID, 'web01', OWNER_PERSON_ID), _person_type())

    assert line == f"Server #{OWNER_OBJECT_ID} - web01"
    assert str(OWNER_PERSON_ID) not in line.split(' - ', 1)[1]


def test_a_person_value_shows_the_labellers_text() -> None:
    """The labeller's text takes the value's place, in declaration order"""
    line: str = compose_summary_line(
        _person_doc(OWNER_OBJECT_ID, 'web01', OWNER_PERSON_ID), _person_type(), labeller=_labels,
    )

    assert line == f"Server #{OWNER_OBJECT_ID} - web01 | {OWNER_PERSON_LABEL}"


def test_a_person_value_the_reader_sees_none_of_is_left_out() -> None:
    """An empty text (no visible person) leaves the field out like any empty value"""
    line: str = compose_summary_line(
        _person_doc(OWNER_OBJECT_ID, 'web01', OWNER_PERSON_ID), _person_type(),
        labeller=lambda values: [''] * len(values),
    )

    assert line == f"Server #{OWNER_OBJECT_ID} - web01"


def test_one_labeller_call_labels_every_line_of_a_batch() -> None:
    """The person values of all lines go to the labeller in one call, each line gets its own text"""
    labeller = MagicMock(side_effect=_labels)
    other_type: MagicMock = _make_type_mock(OTHER_TYPE_ID, 'Switch', has_summaries=True,
                                            summary_fields=[HOSTNAME_FIELD])
    docs: list[dict[str, Any]] = [
        _person_doc(OWNER_OBJECT_ID, 'web01', OWNER_PERSON_ID),
        _person_doc(SECOND_OBJECT_ID, 'web02', SECOND_PERSON_IDS),
        _make_object_doc(OTHER_OBJECT_ID, OTHER_TYPE_ID, fields=[{'name': 'hostname', 'value': 'sw01'}]),
    ]

    lines: dict[int, str] = compose_summary_lines(
        docs, {OWNER_TYPE_ID: _person_type(), OTHER_TYPE_ID: other_type}, labeller=labeller,
    )

    assert lines == {
        OWNER_OBJECT_ID: f"Server #{OWNER_OBJECT_ID} - web01 | {OWNER_PERSON_LABEL}",
        SECOND_OBJECT_ID: f"Server #{SECOND_OBJECT_ID} - web02 | {SECOND_PERSON_LABELS}",
        OTHER_OBJECT_ID: f"Switch #{OTHER_OBJECT_ID} - sw01",
    }
    labeller.assert_called_once_with([OWNER_PERSON_ID, SECOND_PERSON_IDS])


def test_the_labeller_is_not_called_without_a_person_summary_field() -> None:
    """A batch whose types have no person summary field reads nothing more"""
    labeller = MagicMock(side_effect=_labels)
    text_type: MagicMock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True, summary_fields=[HOSTNAME_FIELD])

    compose_summary_lines([_person_doc(OWNER_OBJECT_ID, 'web01', OWNER_PERSON_ID)], {OWNER_TYPE_ID: text_type},
                          labeller=labeller)

    labeller.assert_not_called()


@pytest.mark.parametrize('empty_value', [None, '', []])
def test_the_labeller_is_not_called_for_empty_person_values(empty_value: Any) -> None:
    """No person value to show: no labeller call, and the line has no person part"""
    labeller = MagicMock(side_effect=_labels)

    line: str = compose_summary_line(_person_doc(OWNER_OBJECT_ID, 'web01', empty_value), _person_type(),
                                     labeller=labeller)

    assert line == f"Server #{OWNER_OBJECT_ID} - web01"
    labeller.assert_not_called()


def test_label_person_values_replaces_in_place_and_leaves_other_fields() -> None:
    """Only the named person fields are rewritten; the rest of the values stay as stored"""
    values: dict[str, Any] = {'hostname': 'web01', 'owner': OWNER_PERSON_ID}

    label_person_values([(values, {'owner'})], _labels)

    assert values == {'hostname': 'web01', 'owner': OWNER_PERSON_LABEL}
