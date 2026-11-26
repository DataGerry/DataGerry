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
Unit tests for cmdb.database.field_query_fragments - the field-entry fragments the report builder and the scope compiler
share. Pinned: the $elemMatch and missing-entry shapes, the day widening per operator, the escaped substring and
anchored prefix
"""
from datetime import datetime
from typing import Any

import pytest

from cmdb.database.field_query_fragments import (
    contains_fragment,
    day_granular_fragment,
    elem_match,
    end_of_day,
    no_entry,
    starts_with_fragment,
)
# -------------------------------------------------------------------------------------------------------------------- #

DAY: datetime = datetime(2026, 3, 4)
DAY_END: datetime = datetime(2026, 3, 4, 23, 59, 59, 999999)


def test_elem_match_and_no_entry() -> None:
    """By name; the missing-entry match on any path"""
    assert elem_match('f', {'$eq': 1}) == {'$elemMatch': {'name': 'f', 'value': {'$eq': 1}}}
    assert no_entry('f') == {'fields': {'$not': {'$elemMatch': {'name': 'f'}}}}
    assert no_entry('f', 'rows') == {'rows': {'$not': {'$elemMatch': {'name': 'f'}}}}


@pytest.mark.parametrize('operator, expected', [
    ('$eq', {'$gte': DAY, '$lte': DAY_END}), ('$ne', {'$not': {'$gte': DAY, '$lte': DAY_END}}),
    ('$lte', {'$lte': DAY_END}), ('$gt', {'$gt': DAY_END}), ('$lt', None), ('$gte', None), ('$in', None),
])
def test_day_granular_fragment(operator: str, expected: Any) -> None:
    """Widened where the operator needs it"""
    assert day_granular_fragment(operator, DAY) == expected
    assert end_of_day(DAY) == DAY_END


def test_text_fragments_escape_their_input() -> None:
    """Matched literally; the prefix anchored; case optional"""
    assert contains_fragment('a.*') == {'$regex': 'a\\.\\*'}
    assert contains_fragment('a', case_insensitive=True) == {'$regex': 'a', '$options': 'i'}
    assert starts_with_fragment('(x') == {'$regex': '^\\(x'}
