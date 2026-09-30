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
Unit tests for cmdb.models.category_model.category_types

Pure tests of the tolerant reader every consumer of a stored ``types`` array goes through
"""
from typing import Any

import pytest

from cmdb.models.category_model import is_type_id, readable_type_ids
# -------------------------------------------------------------------------------------------------------------------- #


class TestIsTypeId:
    """What a stored entry has to be to name a CmdbType."""

    @pytest.mark.parametrize('value', [1, 42], ids=['one', 'forty-two'])
    def test_a_positive_integer_is_one(self, value: int) -> None:
        """The only shape a public_id has"""
        assert is_type_id(value)

    @pytest.mark.parametrize('value', [0, -3, True, False, 1.0, '1', None, {'a': 1}, [1]],
                             ids=['zero', 'negative', 'true', 'false', 'float', 'string', 'none', 'dict', 'list'])
    def test_anything_else_is_not(self, value: Any) -> None:
        """A boolean is not the integer it subclasses"""
        assert not is_type_id(value)


class TestReadableTypeIds:
    """A stored types array, read defensively."""

    def test_the_ids_are_kept_in_their_stored_order(self) -> None:
        """Junk is skipped, not reordered around"""
        assert readable_type_ids([3, {'a': 1}, 1, 'x', -2, 2]) == [3, 1, 2]

    @pytest.mark.parametrize('value', [None, 'x', {'a': 1}, 7], ids=['none', 'string', 'dict', 'int'])
    def test_a_value_that_is_no_list_reads_as_empty(self, value: Any) -> None:
        """No array, no types"""
        assert readable_type_ids(value) == []
