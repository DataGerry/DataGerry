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
Unit tests for cmdb.class_schema.ci_explorer_model.cmdb_ci_explorer_profile_schema

Pure Cerberus tests. The two filters are lists of positive integer ids, and they may be empty: an empty
filter is how a profile says "no restriction". Whether an id names an existing type or relation is the
write route's check, not the schema's
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.ci_explorer_model.cmdb_ci_explorer_profile_schema import get_cmdb_ci_explorer_profile_schema
from cmdb.models.ci_explorer_model import CiExplorerProfileKey
# -------------------------------------------------------------------------------------------------------------------- #

PROFILE_NAME: str = 'a-profile'
FILTER_FIELDS: list[str] = [CiExplorerProfileKey.TYPES_FILTER.value, CiExplorerProfileKey.RELATIONS_FILTER.value]


def _validates(document: dict[str, Any]) -> bool:
    """Whether the profile schema accepts the document."""
    return Validator(get_cmdb_ci_explorer_profile_schema()).validate(document)


@pytest.mark.parametrize('field', FILTER_FIELDS)
class TestTheFilterLists:
    """What each filter list accepts."""

    @pytest.mark.parametrize('ids', [[], [1], [1, 2, 3]], ids=['empty', 'one', 'several'])
    def test_positive_integer_ids_and_the_empty_list_are_accepted(self, field: str, ids: list[int]) -> None:
        """Empty means no restriction; otherwise every entry is an id"""
        assert _validates({'name': PROFILE_NAME, field: ids})

    def test_a_missing_or_null_filter_is_accepted(self, field: str) -> None:
        """Both read as no restriction, like the empty list"""
        assert _validates({'name': PROFILE_NAME})
        assert _validates({'name': PROFILE_NAME, field: None})

    @pytest.mark.parametrize('bad_entry', ['1', 0, -1, 1.5, {'id': 1}, [1]])
    def test_an_entry_that_is_no_id_is_refused(self, field: str, bad_entry: Any) -> None:
        """Strings, zero, negatives, fractions, documents and nested lists are not ids"""
        assert not _validates({'name': PROFILE_NAME, field: [bad_entry]})

    def test_one_bad_entry_among_good_ones_is_refused(self, field: str) -> None:
        """The rule applies to every entry, not only the first"""
        assert not _validates({'name': PROFILE_NAME, field: [1, 2, 'three']})
