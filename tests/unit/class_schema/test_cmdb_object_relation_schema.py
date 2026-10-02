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
Unit tests for the ``field_values`` rule of cmdb.class_schema.object_relation_model.cmdb_object_relation_schema

Pure Cerberus tests against the write schema the routes validate with (``purge_unknown``): an entry is an object
with a non-blank ``name`` and any ``value``. That the name is a field the relation declares is the write route's
check, since it needs the relation
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.object_relation_model.cmdb_object_relation import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

FIELD_VALUES_KEY: str = 'field_values'


def _validator() -> Validator:
    """The object relation write schema, as the routes run it"""
    return Validator(build_write_schema(CmdbObjectRelation.SCHEMA), purge_unknown=True)


@pytest.mark.parametrize('field_values', [
    [], [{'name': 'a', 'value': ''}], [{'name': 'a', 'value': None}], [{'name': 'a'}], [{'name': 'a', 'value': [1]}],
], ids=['empty', 'blank-value', 'null-value', 'no-value', 'any-value'])
def test_a_named_entry_is_accepted(field_values: list[Any]) -> None:
    """What the frontend sends, and the value of any shape"""
    validator = _validator()
    validator.validate({FIELD_VALUES_KEY: field_values})

    assert validator.errors.get(FIELD_VALUES_KEY) is None


@pytest.mark.parametrize('entry', ['cable', {'value': 'x'}, {'name': '', 'value': 'x'}, {'name': 3}],
                         ids=['not-an-object', 'no-name', 'blank-name', 'name-no-string'])
def test_an_entry_without_a_usable_name_is_refused(entry: Any) -> None:
    """The name is what the relation's field cascade addresses a value by"""
    validator = _validator()
    validator.validate({FIELD_VALUES_KEY: [entry]})

    assert validator.errors.get(FIELD_VALUES_KEY)


def test_an_unknown_key_inside_an_entry_is_purged() -> None:
    """A name / value pair by design, not the triple an object carries"""
    validator = _validator()
    validator.validate({FIELD_VALUES_KEY: [{'name': 'a', 'value': 1, 'type': 'text'}]})

    assert validator.document[FIELD_VALUES_KEY] == [{'name': 'a', 'value': 1}]
