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
Unit tests for cmdb.utils.helpers
"""
import pytest

from cmdb.utils.helpers import str_to_bool, is_truthy_query_arg
# -------------------------------------------------------------------------------------------------------------------- #


class TestStrToBool:
    """str_to_bool strictly coerces 'true'/'false'/bool and raises on anything else."""

    @pytest.mark.parametrize('value', ['true', 'True', ' TRUE ', True])
    def test_truthy_values(self, value) -> None:
        """Recognised true-ish values coerce to True."""
        assert str_to_bool(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', ' FALSE ', False])
    def test_falsy_values(self, value) -> None:
        """Recognised false-ish values coerce to False."""
        assert str_to_bool(value) is False

    @pytest.mark.parametrize('value', [None, '1', 'yes', 0, 'maybe'])
    def test_unrecognised_raises(self, value) -> None:
        """Unrecognised values raise ValueError."""
        with pytest.raises(ValueError):
            str_to_bool(value)


class TestIsTruthyQueryArg:
    """is_truthy_query_arg leniently interprets query flags without raising."""

    @pytest.mark.parametrize('value', ['true', 'True', ' TRUE ', True])
    def test_truthy(self, value) -> None:
        """true-ish values return True."""
        assert is_truthy_query_arg(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', False])
    def test_falsy(self, value) -> None:
        """false-ish values return False."""
        assert is_truthy_query_arg(value) is False

    @pytest.mark.parametrize('value', [None, '1', 'yes', 'maybe', 0])
    def test_unrecognised_returns_default_false(self, value) -> None:
        """Missing / unrecognised values return the default (False) instead of raising."""
        assert is_truthy_query_arg(value) is False

    def test_custom_default_applied_to_unrecognised(self) -> None:
        """The provided default is returned for unrecognised input."""
        assert is_truthy_query_arg(None, default=True) is True
        assert is_truthy_query_arg('nonsense', default=True) is True

    def test_recognised_value_ignores_default(self) -> None:
        """A recognised value wins over the default."""
        assert is_truthy_query_arg('false', default=True) is False
