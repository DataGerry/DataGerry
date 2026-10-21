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
Unit tests for cmdb.interface.rest_api.responses.helpers.api_projection.APIProjection

Pure data-in/data-out tests (no Flask app context, no database). Covers list/dict/None input
normalization, the include/exclude split by flag truthiness (so no key is silently dropped),
the has_includes/has_excludes flags, and that the derived key sets are stable across reads.
"""
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
# -------------------------------------------------------------------------------------------------------------------- #

# Field-name constants (avoid repeated string literals across the tests)
PUBLIC_ID: str = 'public_id'
LABEL: str = 'label'
NAME: str = 'name'
SECRET: str = 'secret'
INCLUDE: int = 1
EXCLUDE: int = 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                               APIProjection - input                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNormalization:
    """The constructor normalizes list / dict / None input into a projection mapping."""

    def test_list_becomes_all_includes(self) -> None:
        """A list of names is treated as an all-includes projection."""
        projection = APIProjection([PUBLIC_ID, LABEL])

        assert sorted(projection.includes) == sorted([PUBLIC_ID, LABEL])
        assert projection.excludes == []

    def test_none_is_empty_projection(self) -> None:
        """A None projection yields no includes and no excludes."""
        projection = APIProjection(None)

        assert projection.includes == []
        assert projection.excludes == []

    def test_empty_dict_is_empty_projection(self) -> None:
        """An empty dict yields no includes and no excludes."""
        projection = APIProjection({})

        assert projection.includes == []
        assert projection.excludes == []


class TestIncludeExcludeSplit:
    """Keys are split into includes/excludes by the truthiness of their flag."""

    def test_dict_includes(self) -> None:
        """Keys with a truthy flag are includes."""
        projection = APIProjection({PUBLIC_ID: INCLUDE, LABEL: INCLUDE})

        assert sorted(projection.includes) == sorted([PUBLIC_ID, LABEL])
        assert projection.excludes == []

    def test_dict_excludes(self) -> None:
        """Keys with a falsy flag are excludes."""
        projection = APIProjection({SECRET: EXCLUDE})

        assert projection.includes == []
        assert projection.excludes == [SECRET]

    def test_mixed_projection(self) -> None:
        """A mixed projection splits each key onto the correct side."""
        projection = APIProjection({PUBLIC_ID: INCLUDE, SECRET: EXCLUDE})

        assert projection.includes == [PUBLIC_ID]
        assert projection.excludes == [SECRET]

    def test_non_binary_truthy_value_is_included_not_dropped(self) -> None:
        """A truthy non-1 flag (e.g. 2) is classified as an include, never silently dropped."""
        projection = APIProjection({PUBLIC_ID: 2})

        assert projection.includes == [PUBLIC_ID]
        assert projection.excludes == []

    def test_falsy_non_zero_value_is_excluded_not_dropped(self) -> None:
        """A falsy non-0 flag (e.g. None) is classified as an exclude, never silently dropped."""
        projection = APIProjection({SECRET: None})

        assert projection.includes == []
        assert projection.excludes == [SECRET]

    def test_boolean_flags(self) -> None:
        """Boolean flags behave like their int equivalents (True -> include, False -> exclude)."""
        projection = APIProjection({PUBLIC_ID: True, SECRET: False})

        assert projection.includes == [PUBLIC_ID]
        assert projection.excludes == [SECRET]


class TestHasFlags:
    """has_includes / has_excludes report whether each side of the split is non-empty."""

    def test_has_includes_true(self) -> None:
        """has_includes is True when at least one key is included."""
        assert APIProjection([PUBLIC_ID]).has_includes is True

    def test_has_includes_false(self) -> None:
        """has_includes is False for an exclude-only projection."""
        assert APIProjection({SECRET: EXCLUDE}).has_includes is False

    def test_has_excludes_true(self) -> None:
        """has_excludes is True when at least one key is excluded."""
        assert APIProjection({SECRET: EXCLUDE}).has_excludes is True

    def test_has_excludes_false(self) -> None:
        """has_excludes is False for an include-only projection."""
        assert APIProjection([PUBLIC_ID]).has_excludes is False

    def test_both_false_for_empty_projection(self) -> None:
        """Both flags are False when the projection is empty."""
        projection = APIProjection(None)

        assert projection.has_includes is False
        assert projection.has_excludes is False


class TestStability:
    """The derived key sets are computed once and returned consistently."""

    def test_includes_stable_across_reads(self) -> None:
        """Reading includes twice returns the same (cached) list object."""
        projection = APIProjection([PUBLIC_ID, LABEL])

        assert projection.includes is projection.includes

    def test_excludes_stable_across_reads(self) -> None:
        """Reading excludes twice returns the same (cached) list object."""
        projection = APIProjection({SECRET: EXCLUDE})

        assert projection.excludes is projection.excludes

    def test_projection_attribute_exposes_normalized_mapping(self) -> None:
        """The normalized projection mapping is exposed on `projection`."""
        assert APIProjection([PUBLIC_ID]).projection == {PUBLIC_ID: 1}
