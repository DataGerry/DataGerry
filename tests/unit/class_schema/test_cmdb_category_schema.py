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
Unit tests for the ``types`` item rule of cmdb.class_schema.category_model.cmdb_category_schema

Pure Cerberus tests: every entry is a positive integer. That an id names an existing CmdbType, appears
once and sits in no other category is the write route's check, not the schema's
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.category_model import CmdbCategory
# -------------------------------------------------------------------------------------------------------------------- #


def _validates(types: Any) -> bool:
    """Whether the category write schema accepts the list."""
    return Validator(build_write_schema(CmdbCategory.SCHEMA), purge_unknown=True).validate(
        {'name': 'a-category', 'types': types})


@pytest.mark.parametrize('types', [[], [1], [1, 2, 3]], ids=['empty', 'one', 'several'])
def test_positive_integer_ids_are_accepted(types: list[int]) -> None:
    """An empty list is a category without types"""
    assert _validates(types)


@pytest.mark.parametrize('entry', [0, -1, 'x', 1.5, {'a': 1}, [1]],
                         ids=['zero', 'negative', 'string', 'fraction', 'document', 'nested-list'])
def test_an_entry_that_is_no_id_is_refused(entry: Any) -> None:
    """The document case is the one that broke the tree and the uncategorized listing"""
    assert not _validates([1, entry])
