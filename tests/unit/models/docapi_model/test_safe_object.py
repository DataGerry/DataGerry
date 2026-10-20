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
Unit tests for cmdb.models.docapi_model.safe_object.SafeObject

Pure tests (no app context, no database). Covers the missing-object fallback behaviour (attribute
and item access resolve to SafeNull, calls are absorbed), the blank/falsy rendering, and the
dunder guard that keeps copy/pickle working.
"""
import copy
import pickle

from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

NBSP: str = '\u00A0'
HTML_NBSP: str = '&nbsp;'


class TestAccess:
    """Attribute/item/get access on a SafeObject resolves to a SafeNull."""

    def test_getattr_returns_safenull(self) -> None:
        """Attribute access for a non-dunder name returns a SafeNull."""
        assert isinstance(SafeObject().anything, SafeNull)

    def test_getitem_returns_safenull(self) -> None:
        """Indexing returns a SafeNull."""
        assert isinstance(SafeObject()['key'], SafeNull)

    def test_get_returns_safenull(self) -> None:
        """`.get(...)` returns a SafeNull regardless of key/default."""
        assert isinstance(SafeObject().get('key', 'default'), SafeNull)


class TestCallAbsorption:
    """A missing method call in a template must not raise (object(999).type() pattern)."""

    def test_calling_safeobject_returns_safeobject(self) -> None:
        """Calling the SafeObject itself returns a SafeObject."""
        assert isinstance(SafeObject()(), SafeObject)

    def test_missing_method_call_returns_safenull(self) -> None:
        """`.type()` (attribute -> SafeNull, then call) resolves to a SafeNull instead of raising."""
        assert isinstance(SafeObject().type(), SafeNull)

    def test_deep_mixed_call_chain_absorbed(self) -> None:
        """A deep chain mixing attribute/index/call access stays absorbed."""
        assert isinstance(SafeObject().foo().bar['b'].baz(), SafeNull)


class TestRendering:
    """A SafeObject renders as a blank (non-breaking space) and is falsy."""

    def test_str_is_nbsp(self) -> None:
        """str() yields a non-breaking space."""
        assert str(SafeObject()) == NBSP

    def test_repr_is_nbsp(self) -> None:
        """repr() yields a non-breaking space."""
        assert repr(SafeObject()) == NBSP

    def test_html_is_nbsp_entity(self) -> None:
        """__html__() yields the &nbsp; entity."""
        assert SafeObject().__html__() == HTML_NBSP

    def test_is_falsy(self) -> None:
        """A SafeObject is falsy so `{% if object(x) %}` guards treat it as empty."""
        assert bool(SafeObject()) is False


class TestDunderGuard:
    """Dunder probes must fail with AttributeError, not resolve to a SafeNull."""

    def test_missing_dunder_raises_attribute_error(self) -> None:
        """A missing dunder name is not absorbed (getattr default returned)."""
        assert getattr(SafeObject(), '__deepcopy__', None) is None

    def test_deepcopy_works(self) -> None:
        """deepcopy succeeds (would raise/corrupt if the dunder probe were absorbed)."""
        assert isinstance(copy.deepcopy(SafeObject()), SafeObject)

    def test_pickle_roundtrip_works(self) -> None:
        """A SafeObject can be pickled and unpickled."""
        assert isinstance(pickle.loads(pickle.dumps(SafeObject())), SafeObject)
