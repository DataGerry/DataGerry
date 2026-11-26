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
Unit tests for the pure half of field protection (phase 12): the type / template write guard, the Field Protection list
and a group's view of it, and the escalation rule over field classes

Pinned: a write sends class and flag only as stored - a new field none, a changed one refused, an omitted one kept, a
template-owned one passed over; the list answers a template's field under the template with its Types as reach and a
Type's own fields under the Type; a group writes a field on an open Type, by its role on a restricted one, never a
``system`` field; a role granting a class the caller cannot write is beyond reach
"""
from typing import Any

from cmdb.framework.access_engine import build_grants
from cmdb.framework.access_rules import beyond_reach
from cmdb.framework.access_rules.field_protection_rules import (
    FIELD_PROTECTION_MANAGED_MESSAGE,
    protection_problems,
    protection_value,
    template_owned_field_names,
)
from cmdb.framework.access_rules.field_protection_view import field_rows, group_field_access
# -------------------------------------------------------------------------------------------------------------------- #

SERVER, OPEN = 11, 12
TYPE_DOC: dict[str, Any] = {
    'public_id': SERVER, 'name': 'server', 'global_template_ids': ['iso-audit'],
    'fields': [{'name': 'host', 'type': 'text', 'required': True},
               {'name': 'iso', 'type': 'checkbox', 'protection': 'compliance'}],
    'render_meta': {'sections': [{'name': 'main', 'fields': ['host']}, {'name': 'iso-audit', 'fields': ['iso']}]},
}
TEMPLATE_DOC: dict[str, Any] = {'public_id': 3, 'name': 'iso-audit',
                                'fields': [{'name': 'iso', 'type': 'checkbox', 'protection': 'compliance',
                                            'audit_relevant': True}]}


def test_protection_value() -> None:
    """An empty class is none; a flag is on only when true"""
    assert [protection_value('protection', value) for value in ('x', '', None, 3)] == ['x', None, None, None]
    assert [protection_value('audit_relevant', value) for value in (True, 'true', None)] == [True, False, False]


def test_template_owned_field_names() -> None:
    """The fields of the sections named after a claimed template"""
    assert template_owned_field_names(TYPE_DOC) == {'iso'}
    assert template_owned_field_names({}) == set()


def test_a_new_field_carries_none() -> None:
    """A create sending a class is refused, naming the field"""
    fields = [{'name': 'a', 'protection': 'x'}, {'name': 'b', 'audit_relevant': False}]

    assert protection_problems(fields) == [FIELD_PROTECTION_MANAGED_MESSAGE.format(field='a')]
    assert fields == [{'name': 'a'}, {'name': 'b'}]


def test_an_update_keeps_the_stored_values() -> None:
    """Sent as stored passes, omitted is filled, changed is refused"""
    stored = [{'name': 'a', 'protection': 'x', 'audit_relevant': True}, {'name': 'b', 'protection': 'y'}]
    same = [{'name': 'a', 'protection': 'x', 'audit_relevant': True}, {'name': 'b'}]

    assert not protection_problems(same, stored)
    assert same == stored
    assert protection_problems([{'name': 'a', 'protection': 'z'}], stored) == [
        FIELD_PROTECTION_MANAGED_MESSAGE.format(field='a')]


def test_a_template_owned_field_is_not_judged() -> None:
    """The reconciliation wrote it"""
    fields = [{'name': 'iso', 'protection': 'compliance'}]

    assert not protection_problems(fields, [], {'iso'})
    assert fields == [{'name': 'iso', 'protection': 'compliance'}]


def test_the_list_answers_each_field_where_it_is_defined() -> None:
    """The template's field once with its reach; the Type's own field under the Type"""
    rows = field_rows([TYPE_DOC, {'public_id': OPEN, 'name': 'open', 'fields': []}], [TEMPLATE_DOC])

    assert [(row['source'], row['source_id'], row['name'], row['reach']) for row in rows] == [
        ('template', 3, 'iso', [SERVER]), ('type', SERVER, 'host', [SERVER])]
    assert (rows[0]['protection'], rows[0]['audit_relevant'], rows[1]['required']) == ('compliance', True, True)


def _grants(classes: list[str], regular: bool = True) -> Any:
    """The group's one assignment on the server Type"""
    return build_grants([{'public_id': 1, 'group_id': 7, 'role_id': 2, 'scope': '*'}],
                        [{'public_id': 2, 'types': [SERVER], 'operations': ['view', 'edit'],
                          'write_regular_fields': regular, 'field_classes': classes}], [7])


def test_a_group_s_view() -> None:
    """Write by the role on a restricted Type, write on an open Type, system never; required only when written"""
    row = {'protection': 'compliance', 'required': True, 'reach': [SERVER, OPEN]}

    assert group_field_access(_grants([]), row) == [{'type_id': SERVER, 'access': 'read', 'required': False},
                                                    {'type_id': OPEN, 'access': 'write', 'required': True}]
    assert group_field_access(_grants(['compliance']), row)[0]['access'] == 'write'
    assert group_field_access(_grants(['system']), {**row, 'protection': 'system'})[0]['access'] == 'system'


def test_a_class_beyond_the_caller_s_reach() -> None:
    """The caller writes regular fields only - a role granting compliance on the server Type is beyond"""
    role = {'types': [SERVER], 'operations': ['edit'], 'write_regular_fields': False, 'field_classes': ['compliance']}

    assert beyond_reach(_grants([]), role) == ["writing the field class 'compliance' on Types [11]"]
    assert not beyond_reach(_grants(['compliance']), role)
