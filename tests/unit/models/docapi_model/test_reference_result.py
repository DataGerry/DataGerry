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
Unit tests for cmdb.models.docapi_model.reference_result.ReferenceResult

Pure tests (no app context, no database). Covers item/attribute/get access with render-safe
wrapping of missing keys, nested dicts and lists, the type() filter, the copy/pickle dunder guard,
and the datetime-safe __repr__.
"""
import copy
import pickle
from datetime import datetime

from cmdb.models.docapi_model.reference_result import ReferenceResult
from cmdb.models.docapi_model.safe_dict import SafeDict
from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: str = 'type_id'
LABEL: str = 'label'
NESTED: str = 'nested'
ITEMS: str = 'items'
INNER: str = 'inner'
MATCHING_TYPE: int = 5
OTHER_TYPE: int = 999


def _sample() -> ReferenceResult:
    """Returns a ReferenceResult wrapping a typed object with a nested dict, a list and a scalar."""
    return ReferenceResult({
        TYPE_ID: MATCHING_TYPE,
        LABEL: 'srv',
        NESTED: {INNER: 1},
        ITEMS: [{INNER: 2}, 'scalar'],
    })


class TestInit:
    """Construction normalizes a None payload to an empty dict."""

    def test_none_becomes_empty_dict(self) -> None:
        """A None obj_data becomes an empty dict."""
        assert ReferenceResult(None).obj_data == {}


class TestItemAccess:
    """__getitem__ returns render-safe values."""

    def test_present_scalar(self) -> None:
        """A present scalar field is returned unchanged."""
        assert _sample()[LABEL] == 'srv'

    def test_present_dict_wrapped(self) -> None:
        """A present nested dict is wrapped as a SafeDict."""
        assert isinstance(_sample()[NESTED], SafeDict)

    def test_missing_key_is_empty_safedict(self) -> None:
        """A missing key resolves to an empty SafeDict, whose own misses resolve to SafeNull."""
        missing = _sample()['absent']

        assert isinstance(missing, SafeDict)
        assert isinstance(missing['deep'], SafeNull)

    def test_list_elements_wrapped(self) -> None:
        """A list field keeps its shape with each dict element wrapped as a SafeDict."""
        items = _sample()[ITEMS]

        assert isinstance(items, list)
        assert isinstance(items[0], SafeDict)
        assert items[1] == 'scalar'


class TestAttributeAccess:
    """__getattr__ mirrors item access, with a dunder guard."""

    def test_present_field_via_attribute(self) -> None:
        """A present field is reachable via attribute access."""
        assert _sample().label == 'srv'

    def test_missing_field_via_attribute_is_empty_safedict(self) -> None:
        """A missing field via attribute resolves to an empty SafeDict."""
        assert isinstance(_sample().absent, SafeDict)

    def test_dunder_attribute_raises(self) -> None:
        """A missing dunder name raises AttributeError (protocol probes not absorbed)."""
        assert getattr(_sample(), '__deepcopy__', None) is None


class TestGet:
    """get() mirrors __getitem__ but honours an explicit default."""

    def test_present(self) -> None:
        """get returns a present value."""
        assert _sample().get(LABEL) == 'srv'

    def test_missing_is_empty_safedict(self) -> None:
        """A missing key with no default resolves to an empty SafeDict, not None (render-safe)."""
        result = _sample().get('absent')

        assert isinstance(result, SafeDict)
        assert isinstance(result['deep'], SafeNull)

    def test_missing_scalar_default_returned(self) -> None:
        """A scalar default is returned unchanged for a missing key."""
        assert _sample().get('absent', 'fallback') == 'fallback'

    def test_missing_dict_default_wrapped(self) -> None:
        """A dict default is wrapped as a SafeDict."""
        assert isinstance(_sample().get('absent', {INNER: 1}), SafeDict)


class TestTypeFilter:
    """type() returns the data only when the type matches."""

    def test_matching_type_returns_data(self) -> None:
        """A matching type_id returns the object's data as a SafeDict."""
        result = _sample().type(MATCHING_TYPE)

        assert isinstance(result, SafeDict)
        assert result[LABEL] == 'srv'

    def test_non_matching_type_returns_empty(self) -> None:
        """A non-matching type_id returns an empty SafeDict."""
        result = _sample().type(OTHER_TYPE)

        assert isinstance(result, SafeDict)
        assert result == {}

    def test_empty_object_returns_empty(self) -> None:
        """An empty ReferenceResult never matches a type."""
        assert ReferenceResult(None).type(MATCHING_TYPE) == {}


class TestReprAndCopy:
    """__repr__ is datetime-safe and the object survives copy/pickle."""

    def test_repr_does_not_raise_on_datetime(self) -> None:
        """__repr__ coerces non-JSON-serializable values (e.g. datetime) via str instead of raising."""
        rendered = repr(ReferenceResult({'when': datetime(2026, 1, 1)}))

        assert 'ReferenceResult' in rendered

    def test_deepcopy_works(self) -> None:
        """deepcopy succeeds and preserves the data."""
        copied = copy.deepcopy(_sample())

        assert isinstance(copied, ReferenceResult)
        assert copied[LABEL] == 'srv'

    def test_pickle_roundtrip_works(self) -> None:
        """A ReferenceResult survives a pickle round-trip."""
        restored = pickle.loads(pickle.dumps(_sample()))

        assert restored[LABEL] == 'srv'
