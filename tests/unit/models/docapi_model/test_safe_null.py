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
Unit tests for cmdb.models.docapi_model.safe_null.SafeNull

Pure tests (no app context, no database). Covers the null-object absorption behaviour (indexing,
attribute lookup, `.get`, `.type` all return self), the blank/falsy rendering, and the dunder
guard that lets copy/pickle protocol probes fail normally.
"""
import copy
import pickle

from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

NBSP: str = '\u00A0'
HTML_NBSP: str = '&nbsp;'


class TestAbsorption:
    """Any access on a SafeNull returns a SafeNull, so nested lookups never raise."""

    def test_getitem_returns_safenull(self) -> None:
        """Indexing a SafeNull returns a SafeNull."""
        assert isinstance(SafeNull()['anything'], SafeNull)

    def test_getattr_returns_safenull(self) -> None:
        """Attribute access for a non-dunder name returns a SafeNull."""
        assert isinstance(SafeNull().anything, SafeNull)

    def test_get_returns_safenull(self) -> None:
        """`.get(...)` returns a SafeNull regardless of key/default."""
        assert isinstance(SafeNull().get('key', 'default'), SafeNull)

    def test_type_returns_safenull(self) -> None:
        """`.type(...)` returns a SafeNull (absorbs a field literally named 'type')."""
        assert isinstance(SafeNull().type('x'), SafeNull)

    def test_call_returns_safenull(self) -> None:
        """Calling a SafeNull returns a SafeNull, so a missing method call never raises."""
        assert isinstance(SafeNull()('arg', kw=1), SafeNull)

    def test_deep_chain_absorbed(self) -> None:
        """A deep mixed chain of attribute/index/get access stays absorbed."""
        result = SafeNull().a.b['c'].get('d').e[0]

        assert isinstance(result, SafeNull)


class TestRendering:
    """A SafeNull renders as a blank (non-breaking space) and is falsy."""

    def test_str_is_nbsp(self) -> None:
        """str() yields a non-breaking space."""
        assert str(SafeNull()) == NBSP

    def test_repr_is_nbsp(self) -> None:
        """repr() yields a non-breaking space."""
        assert repr(SafeNull()) == NBSP

    def test_html_is_nbsp_entity(self) -> None:
        """__html__() yields the &nbsp; entity for template escaping."""
        assert SafeNull().__html__() == HTML_NBSP

    def test_is_falsy(self) -> None:
        """A SafeNull is falsy so `{% if value %}` guards treat it as empty."""
        assert bool(SafeNull()) is False


class TestDunderGuard:
    """Dunder probes must fail with AttributeError, not receive a SafeNull."""

    def test_missing_dunder_raises_attribute_error(self) -> None:
        """A missing dunder name raises AttributeError instead of returning self."""
        probe = getattr(SafeNull(), '__deepcopy__', None)

        assert probe is None

    def test_deepcopy_works(self) -> None:
        """deepcopy succeeds (would raise TypeError if the dunder probe got a SafeNull)."""
        assert isinstance(copy.deepcopy(SafeNull()), SafeNull)

    def test_pickle_roundtrip_works(self) -> None:
        """A SafeNull can be pickled and unpickled."""
        assert isinstance(pickle.loads(pickle.dumps(SafeNull())), SafeNull)
