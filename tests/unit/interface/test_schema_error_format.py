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
Unit tests for cmdb.interface.blueprints.schema_error_format

The reason a schema-refused request body is answered with: the Cerberus error tree flattened to one
``path: reason`` line per failure (nested documents as ``field.child``, list items as ``field[1]``),
bounded to ``MAX_REPORTED_SCHEMA_ERRORS`` with a count of the rest, and led by the fixed text
"""
from cmdb.interface.blueprints.api_blueprint_constants import INVALID_BODY_MESSAGE, MAX_REPORTED_SCHEMA_ERRORS
from cmdb.interface.blueprints.schema_error_format import describe_schema_errors, flatten_schema_errors
# -------------------------------------------------------------------------------------------------------------------- #

EMPTY_REASON: str = 'empty values not allowed'
REQUIRED_REASON: str = 'required field'


def test_a_top_level_field_is_named_with_its_reason() -> None:
    """The simplest tree: one field, one broken rule."""
    assert flatten_schema_errors({'assigned_ids': [EMPTY_REASON]}) == [f'assigned_ids: {EMPTY_REASON}']


def test_a_field_with_two_broken_rules_gets_two_lines() -> None:
    """Every message of a field is reported, not just the first."""
    assert flatten_schema_errors({'name': ['a', 'b']}) == ['name: a', 'name: b']


def test_a_list_item_is_written_with_its_index() -> None:
    """Cerberus keys a failing list item by its integer index."""
    errors = {'fields': [{1: [{'name': [REQUIRED_REASON]}]}]}

    assert flatten_schema_errors(errors) == [f'fields[1].name: {REQUIRED_REASON}']


def test_a_nested_document_is_written_with_a_dot() -> None:
    """A sub-document's field is addressed through its parent."""
    errors = {'acl': [{'activated': ['must be of boolean type']}]}

    assert flatten_schema_errors(errors) == ['acl.activated: must be of boolean type']


def test_fields_are_reported_in_a_stable_order() -> None:
    """The same refusal always answers the same text, whatever order Cerberus built the tree in."""
    assert flatten_schema_errors({'b': ['x'], 'a': ['y']}) == ['a: y', 'b: x']


def test_the_message_leads_with_the_fixed_text() -> None:
    """A client can tell a schema refusal from a route's own 400."""
    message = describe_schema_errors({'assigned_ids': [EMPTY_REASON]})

    assert message == f'{INVALID_BODY_MESSAGE}: assigned_ids: {EMPTY_REASON}'


def test_the_message_is_bounded_and_counts_the_rest() -> None:
    """A body refused for many items names the first few and says how many more there are."""
    errors = {f'field{index:02d}': [REQUIRED_REASON] for index in range(MAX_REPORTED_SCHEMA_ERRORS + 3)}

    message = describe_schema_errors(errors)

    assert message.count(REQUIRED_REASON) == MAX_REPORTED_SCHEMA_ERRORS
    assert message.endswith('and 3 more')


def test_an_empty_tree_still_answers_the_lead_text() -> None:
    """A refusal Cerberus gives no reason for still reads as a refusal."""
    assert describe_schema_errors({}) == f'{INVALID_BODY_MESSAGE}!'
