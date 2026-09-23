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

from cmdb.manager.objects_summary_helper import compose_summary_line
# -------------------------------------------------------------------------------------------------------------------- #

OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50


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


def test_compose_summary_line_falls_back_to_default_when_field_walk_raises() -> None:
    """An exception while walking summary fields produces the default prefix and does not raise"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)  # 'fields' is []
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True)
    type_mock.get_summary.side_effect = RuntimeError('boom')

    result = compose_summary_line(obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


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
