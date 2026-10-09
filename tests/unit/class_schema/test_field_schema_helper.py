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
Unit tests for cmdb.class_schema.field_schema_helper

The shared field-definition rules are declared once and merged into both the CmdbType and the CmdbRelation
``fields`` entry, so what is pinned here is that both schemas carry them unchanged and that a caller cannot change the
other's copy
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.field_schema_helper import get_field_definition_rules
from cmdb.class_schema.relation_model.cmdb_relation_schema import get_cmdb_relation_schema
from cmdb.class_schema.type_model.cmdb_type_schema import get_cmdb_type_schema
# -------------------------------------------------------------------------------------------------------------------- #

SHARED_KEYS: set[str] = {'rows', 'description', 'regex', 'placeholder', 'value', 'helperText', 'options'}
FIELDS_KEY: str = 'fields'


def _field_entry_rules(schema: dict[str, Any]) -> dict[str, Any]:
    """The rules of one ``fields`` entry of a document schema."""
    return schema[FIELDS_KEY]['schema']['schema']


def test_the_shared_keys_are_the_declared_ones() -> None:
    """Nothing more and nothing less is shared"""
    assert set(get_field_definition_rules()) == SHARED_KEYS


@pytest.mark.parametrize('build_schema', [get_cmdb_type_schema, get_cmdb_relation_schema], ids=['type', 'relation'])
def test_each_schema_carries_the_shared_rules_unchanged(build_schema: Any) -> None:
    """Merged as declared - neither schema overrides a shared key"""
    entry = _field_entry_rules(build_schema())
    shared = get_field_definition_rules()

    assert {key: entry[key] for key in SHARED_KEYS} == shared


def test_every_call_answers_a_new_dict() -> None:
    """A schema that changes its copy changes nobody else's"""
    first = get_field_definition_rules()
    first['options']['schema']['schema']['name']['required'] = False

    assert get_field_definition_rules()['options']['schema']['schema']['name']['required'] is True


def test_the_option_rules_still_validate() -> None:
    """An option needs both name and label; the rules are usable as a Cerberus schema"""
    validator = Validator(get_field_definition_rules())

    assert validator.validate({'options': [{'name': 'a', 'label': 'A'}]})
    assert not validator.validate({'options': [{'name': 'a'}]})
