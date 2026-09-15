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
Unit tests for cmdb.open_celium.oc_helpers

map_oc_name / unmap_oc_name scope OpenCelium object titles to a tenant by prefixing them with the
database name and stripping that prefix again.
"""
import pytest

from cmdb.open_celium.oc_helpers import map_oc_name, unmap_oc_name
# -------------------------------------------------------------------------------------------------------------------- #


class TestMapOcName:
    """map_oc_name prefixes the input with the map name."""

    def test_prefixes_with_map_name(self) -> None:
        """The result is '<map_name>_<input_str>'."""
        assert map_oc_name('gfSKkjoRzAxJwC', 'my-connection') == 'gfSKkjoRzAxJwC_my-connection'


class TestUnmapOcName:
    """unmap_oc_name strips the leading '<map_name>_' prefix."""

    def test_strips_prefix(self) -> None:
        """The part after the first underscore is returned."""
        assert unmap_oc_name('gfSKkjoRzAxJwC_my-connection') == 'my-connection'

    def test_round_trip(self) -> None:
        """unmap reverses map for a plain value."""
        mapped = map_oc_name('db', 'conn')
        assert unmap_oc_name(mapped) == 'conn'

    def test_round_trip_value_with_underscores(self) -> None:
        """A value that itself contains underscores is restored intact (only the prefix is stripped)."""
        mapped = map_oc_name('db', 'my_special_conn')
        assert unmap_oc_name(mapped) == 'my_special_conn'

    def test_no_underscore_strict_raises(self) -> None:
        """A string without an underscore raises ValueError in strict (default) mode."""
        with pytest.raises(ValueError):
            unmap_oc_name('nounderscore')

    def test_no_underscore_non_strict_returns_unchanged(self) -> None:
        """A string without an underscore is returned unchanged when strict is False."""
        assert unmap_oc_name('nounderscore', strict=False) == 'nounderscore'
