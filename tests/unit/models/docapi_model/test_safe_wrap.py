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
Unit tests for cmdb.models.docapi_model.safe_wrap.safe_wrap

Pure tests (no app context, no database). Covers the recursive wrapping of dicts (-> SafeDict),
lists, nested structures, and the pass-through of scalar values.
"""
from cmdb.models.docapi_model.safe_wrap import safe_wrap
from cmdb.models.docapi_model.safe_dict import SafeDict
from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

INNER: str = 'inner'


class TestSafeWrap:
    """safe_wrap converts dicts/lists to render-safe structures and passes scalars through."""

    def test_dict_becomes_safedict(self) -> None:
        """A dict is wrapped as a SafeDict."""
        assert isinstance(safe_wrap({INNER: 1}), SafeDict)

    def test_nested_dict_wrapped_recursively(self) -> None:
        """A nested dict is wrapped and its missing keys resolve to a SafeNull."""
        wrapped = safe_wrap({'outer': {INNER: 1}})

        assert isinstance(wrapped['outer'], SafeDict)
        assert wrapped['outer'][INNER] == 1
        assert isinstance(wrapped['outer']['absent'], SafeNull)

    def test_list_elements_wrapped(self) -> None:
        """Each element of a list is wrapped recursively."""
        wrapped = safe_wrap([{INNER: 1}, 'scalar'])

        assert isinstance(wrapped, list)
        assert isinstance(wrapped[0], SafeDict)
        assert wrapped[1] == 'scalar'

    def test_scalar_passthrough(self) -> None:
        """A scalar value is returned unchanged."""
        assert safe_wrap(7) == 7

    def test_none_passthrough(self) -> None:
        """A top-level None is returned unchanged (only dict/list are wrapped)."""
        assert safe_wrap(None) is None
