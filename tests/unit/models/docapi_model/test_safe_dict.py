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
Unit tests for cmdb.models.docapi_model.safe_dict.SafeDict

Pure tests (no app context, no database). Covers item/attribute/get access for present, missing
and None values, the recursive wrapping of nested dicts and lists (_wrap), the intended
SafeNull-for-missing render semantics, and the dunder guard that keeps copy/pickle working.
"""
import copy
import pickle

from cmdb.models.docapi_model.safe_dict import SafeDict
from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

# Field-name constants (avoid repeated string literals across the tests)
PRESENT: str = 'present'
MISSING: str = 'missing'
NESTED: str = 'nested'
ITEMS: str = 'items'
NOTHING: str = 'nothing'
INNER: str = 'inner'


def _sample() -> SafeDict:
    """Returns a fresh SafeDict with a scalar, a nested dict, a list of dicts and a None value."""
    return SafeDict({
        PRESENT: 1,
        NESTED: {INNER: 2},
        ITEMS: [{INNER: 3}],
        NOTHING: None,
    })


# -------------------------------------------------------------------------------------------------------------------- #
#                                              SafeDict.__getitem__                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetItem:
    """Indexing returns wrapped values, or a SafeNull for missing keys / None."""

    def test_present_scalar(self) -> None:
        """A present scalar is returned unchanged."""
        assert _sample()[PRESENT] == 1

    def test_missing_key_is_safenull(self) -> None:
        """A missing key resolves to a SafeNull instead of raising KeyError."""
        assert isinstance(_sample()[MISSING], SafeNull)

    def test_none_value_is_safenull(self) -> None:
        """A stored None resolves to a SafeNull."""
        assert isinstance(_sample()[NOTHING], SafeNull)

    def test_nested_dict_wrapped(self) -> None:
        """A nested dict is wrapped as a SafeDict, and its missing keys are also safe."""
        nested = _sample()[NESTED]

        assert isinstance(nested, SafeDict)
        assert nested[INNER] == 2
        assert isinstance(nested[MISSING], SafeNull)

    def test_list_elements_wrapped(self) -> None:
        """A list value stays a list, with each dict element wrapped."""
        items = _sample()[ITEMS]

        assert isinstance(items, list)
        assert isinstance(items[0], SafeDict)
        assert items[0][INNER] == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SafeDict.get                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGet:
    """get() mirrors indexing but honours a provided default (wrapped)."""

    def test_present(self) -> None:
        """get returns the present value."""
        assert _sample().get(PRESENT) == 1

    def test_missing_defaults_to_safenull(self) -> None:
        """A missing key with no default resolves to a SafeNull, not None."""
        assert isinstance(_sample().get(MISSING), SafeNull)

    def test_missing_explicit_none_default_is_safenull(self) -> None:
        """An explicit None default still resolves to a SafeNull (render-safe semantics)."""
        assert isinstance(_sample().get(MISSING, None), SafeNull)

    def test_missing_dict_default_is_wrapped(self) -> None:
        """A dict default is wrapped as a SafeDict."""
        assert isinstance(_sample().get(MISSING, {INNER: 1}), SafeDict)

    def test_missing_scalar_default_returned(self) -> None:
        """A scalar default is returned unchanged."""
        assert _sample().get(MISSING, 'fallback') == 'fallback'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              SafeDict.__getattr__                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetAttr:
    """Attribute access maps to keys, with a SafeNull for misses and a dunder guard."""

    def test_present_key_via_attribute(self) -> None:
        """A present key is reachable via attribute access."""
        assert _sample().present == 1

    def test_missing_attribute_is_safenull(self) -> None:
        """A non-key attribute resolves to a SafeNull."""
        assert isinstance(_sample().missing, SafeNull)

    def test_real_dict_method_still_accessible(self) -> None:
        """A real dict method (keys) is not shadowed by __getattr__."""
        assert set(_sample().keys()) == {PRESENT, NESTED, ITEMS, NOTHING}

    def test_dunder_attribute_raises(self) -> None:
        """A missing dunder name raises AttributeError (so protocol probes fail normally)."""
        assert getattr(_sample(), '__deepcopy__', None) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SafeDict._wrap                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWrap:
    """_wrap converts None/dict/list appropriately and passes other values through."""

    def test_none_to_safenull(self) -> None:
        """None wraps to a SafeNull."""
        assert isinstance(SafeDict()._wrap(None), SafeNull)

    def test_plain_dict_to_safedict(self) -> None:
        """A plain dict wraps to a SafeDict."""
        assert isinstance(SafeDict()._wrap({INNER: 1}), SafeDict)

    def test_existing_safedict_not_rewrapped(self) -> None:
        """An already-SafeDict value is returned as-is (no double wrap)."""
        inner = SafeDict({INNER: 1})

        assert SafeDict()._wrap(inner) is inner

    def test_list_elements_wrapped(self) -> None:
        """Each element of a list is wrapped recursively."""
        wrapped = SafeDict()._wrap([{INNER: 1}, None])

        assert isinstance(wrapped, list)
        assert isinstance(wrapped[0], SafeDict)
        assert isinstance(wrapped[1], SafeNull)

    def test_scalar_passthrough(self) -> None:
        """A scalar is returned unchanged."""
        assert SafeDict()._wrap(7) == 7


# -------------------------------------------------------------------------------------------------------------------- #
#                                            SafeDict copy / pickle                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCopyPickle:
    """The dunder guard keeps copy/pickle working on a SafeDict."""

    def test_deepcopy_works(self) -> None:
        """deepcopy succeeds and preserves the data and type."""
        copied = copy.deepcopy(_sample())

        assert isinstance(copied, SafeDict)
        assert copied[PRESENT] == 1

    def test_pickle_roundtrip_works(self) -> None:
        """A SafeDict survives a pickle round-trip."""
        restored = pickle.loads(pickle.dumps(_sample()))

        assert restored[PRESENT] == 1
