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
Unit tests for cmdb.models.docapi_model.aggregated_fields.AggregatedFields

Pure tests: indexing aggregates a field across several dicts, skipping missing and empty values and
coercing the survivors to a comma-separated string.
"""
from cmdb.models.docapi_model.aggregated_fields import AggregatedFields
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'city'


class TestGetItem:
    """__getitem__ joins the non-empty values of a field across all dicts."""

    def test_joins_present_values(self) -> None:
        """Values present in several dicts are joined by ', ' in order."""
        aggregated = AggregatedFields([{FIELD: 'NYC'}, {FIELD: 'LA'}])

        assert aggregated[FIELD] == 'NYC, LA'

    def test_skips_missing_and_empty(self) -> None:
        """Dicts missing the field, or holding None / empty string, are skipped."""
        aggregated = AggregatedFields([{FIELD: 'NYC'}, {}, {FIELD: None}, {FIELD: ''}, {FIELD: 'LA'}])

        assert aggregated[FIELD] == 'NYC, LA'

    def test_coerces_non_string_values(self) -> None:
        """Non-string values are coerced via str before joining."""
        aggregated = AggregatedFields([{FIELD: 1}, {FIELD: 2}])

        assert aggregated[FIELD] == '1, 2'

    def test_zero_is_kept(self) -> None:
        """A numeric zero is a real value and is not treated as empty."""
        aggregated = AggregatedFields([{FIELD: 0}])

        assert aggregated[FIELD] == '0'

    def test_empty_returns_empty_string(self) -> None:
        """No dicts (or no matching values) yields an empty string."""
        assert AggregatedFields([])[FIELD] == ''
