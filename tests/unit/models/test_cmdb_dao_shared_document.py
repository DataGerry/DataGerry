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
Unit tests for the shared from_data / to_json on cmdb.models.cmdb_dao.CmdbDAO

Pure tests: no Mongo, no Flask. A model that declares ``KEYS`` plus its two error types inherits both
methods instead of writing its own copy - the lift that replaced eleven byte-identical
``__init__``/``from_data``/``to_json`` triples in the ISMS family, each with its own three untested
``except`` arms (discussion-backlog #206).

What is pinned here is the contract of that shared pair, exercised against a local model built for the
purpose rather than against a real one, so the base class is tested on its own terms:

  - the round trip is over exactly the enum's keys, in the enum's order
  - ``public_id`` is read through ``get_public_id()``, every other key through its attribute
  - the ``normalize_document`` hook runs first, and edits the document in place
  - the instance is type-checked, which is what keeps two structurally identical models from
    serialising as each other
  - ``REQUIRED_INIT_KEYS`` is enforced against the DOCUMENT, which is how a model keeps the strictness
    of reading a key with ``data['key']``
  - each failure surfaces as the declaring model's own error type, from the base class
  - a model that declares no ``KEYS`` still gets the NotImplementedError it always did
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 77
LABEL: str = 'a label'


class _ThingKey(BaseStrEnum):
    """Document keys of the local test model"""
    PUBLIC_ID = 'public_id'
    LABEL = 'label'
    TAGS = 'tags'


class _ThingInitError(Exception):
    """Raised when the local test model cannot be initialised"""


class _ThingFromDataError(Exception):
    """Raised when the local test model cannot be built from a document"""


class _ThingToJsonError(Exception):
    """Raised when the local test model cannot be serialised"""


class _Thing(CmdbDAO):
    """
    A minimal CmdbDAO sharing both document methods

    Declares the three attributes the shared pair needs and nothing else, so a failure here is the base
    class's and not some real model's.

    `Extends`: CmdbDAO
    """
    COLLECTION = 'test.things'

    KEYS = _ThingKey
    INIT_FROM_DATA_ERROR = _ThingFromDataError
    TO_JSON_ERROR = _ThingToJsonError

    def __init__(self, *, public_id: int, label: str, tags: list[str] | None = None) -> None:
        """
        Initialises a _Thing

        Args:
            public_id (int): public_id of the _Thing
            label (str): Its label
            tags (list[str], optional): Its tags, coerced to a list the way the ISMS models do
        """
        try:
            self.label = label
            self.tags = tags or []

            super().__init__(public_id = public_id)
        except Exception as err:
            raise _ThingInitError(err) from err


class _StrictThing(_Thing):
    """
    A _Thing whose document must carry its label

    `Extends`: _Thing
    """
    REQUIRED_INIT_KEYS: list[str] = [_ThingKey.LABEL.value]


class _TwinThing(CmdbDAO):
    """
    A different model with the very same field names - the mix-up the type check exists for

    `Extends`: CmdbDAO
    """
    COLLECTION = 'test.twins'

    KEYS = _ThingKey
    INIT_FROM_DATA_ERROR = _ThingFromDataError
    TO_JSON_ERROR = _ThingToJsonError

    def __init__(self, *, public_id: int, label: str, tags: list[str] | None = None) -> None:
        """
        Initialises a _TwinThing

        Args:
            public_id (int): public_id of the _TwinThing
            label (str): Its label
            tags (list[str], optional): Its tags
        """
        self.label = label
        self.tags = tags or []

        super().__init__(public_id = public_id)


class _NormalisingThing(_Thing):
    """
    A _Thing whose document needs massaging first

    `Extends`: _Thing
    """
    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Uppercases the label in place

        Args:
            data (dict[str, Any]): The document, edited in place
        """
        if data.get(_ThingKey.LABEL.value):
            data[_ThingKey.LABEL.value] = data[_ThingKey.LABEL.value].upper()


class _KeylessThing(CmdbDAO):
    """
    A CmdbDAO that shares neither method

    `Extends`: CmdbDAO
    """
    COLLECTION = 'test.keyless'


def _document(**overrides: Any) -> dict[str, Any]:
    """
    Builds a complete _Thing document

    Args:
        **overrides: Keys to replace in the returned document

    Returns:
        dict[str, Any]: A document carrying every _ThingKey
    """
    document: dict[str, Any] = {
        _ThingKey.PUBLIC_ID.value: PUBLIC_ID,
        _ThingKey.LABEL.value: LABEL,
        _ThingKey.TAGS.value: ['x'],
    }
    document.update(overrides)

    return document


class TestSharedRoundTrip:
    """from_data and to_json are a round trip over exactly the declared keys."""

    def test_round_trip_returns_the_document(self) -> None:
        """A document in, the same document out."""
        document = _document()

        assert _Thing.to_json(_Thing.from_data(document)) == document

    def test_to_json_emits_the_keys_in_the_enums_order(self) -> None:
        """The enum's order is the payload's order, which is why it starts with public_id."""
        payload = _Thing.to_json(_Thing.from_data(_document()))

        assert list(payload) == [key.value for key in _ThingKey]

    def test_a_key_missing_from_the_document_becomes_none(self) -> None:
        """from_data reads every key with .get, so the constructor decides what an absent one means."""
        document = _document()
        del document[_ThingKey.TAGS.value]

        # The constructor's own `tags or []` is what turns that None into a list
        assert _Thing.from_data(document).tags == []

    def test_a_value_outside_the_keys_is_dropped(self) -> None:
        """The key set is closed: an extra key reaches neither the constructor nor the payload."""
        payload = _Thing.to_json(_Thing.from_data(_document(surprise='ignored')))

        assert 'surprise' not in payload

    def test_public_id_is_read_through_the_accessor(self) -> None:
        """get_public_id refuses an unassigned id, which a plain attribute read would not."""
        thing = _Thing.from_data(_document(public_id=0))

        with pytest.raises(_ThingToJsonError):
            _Thing.to_json(thing)


class TestNormalizeDocumentHook:
    """The hook is where a per-field rule lives that a key list cannot express."""

    def test_the_hook_runs_before_the_constructor(self) -> None:
        """The normalised value is what the instance carries."""
        assert _NormalisingThing.from_data(_document()).label == LABEL.upper()

    def test_the_hook_edits_the_given_document(self) -> None:
        """In place by design: a write route hands the same dict on to be stored."""
        document = _document()

        _NormalisingThing.from_data(document)

        assert document[_ThingKey.LABEL.value] == LABEL.upper()

    def test_the_default_hook_changes_nothing(self) -> None:
        """A model whose keys need no massaging declares nothing."""
        document = _document()

        _Thing.from_data(document)

        assert document == _document()


class TestSharedErrorArms:
    """Both methods convert their failure into the declaring model's own error type."""

    def test_from_data_error_on_an_unusable_document(self) -> None:
        """An empty dict has no public_id, and int(None) is what fails."""
        with pytest.raises(_ThingFromDataError):
            _Thing.from_data({})

    def test_from_data_error_when_the_document_is_not_a_dict(self) -> None:
        """A None document fails on .get, in the same arm."""
        with pytest.raises(_ThingFromDataError):
            _Thing.from_data(None)

    def test_to_json_error_when_the_instance_is_not_one(self) -> None:
        """Reading an attribute the instance does not carry is a ToJsonError."""
        with pytest.raises(_ThingToJsonError):
            _Thing.to_json(SimpleNamespace())


class TestTheInstanceIsTypeChecked:
    """Two models with the same field names would otherwise serialise as each other."""

    def test_a_twin_model_is_refused(self) -> None:
        """
        The real case this guards: IsmsImpact and IsmsLikelihood carry the very same four keys

        Before the check was lifted into CmdbDAO only IsmsImpact had it, so
        ``IsmsLikelihood.to_json(an_impact)`` returned an impact serialised as a likelihood.
        """
        twin = _TwinThing.from_data(_document())

        with pytest.raises(_ThingToJsonError, match='_Thing'):
            _Thing.to_json(twin)

    def test_a_subclass_is_accepted(self) -> None:
        """isinstance, not type equality: a subclass is still the model it extends."""
        normalising = _NormalisingThing.from_data(_document())

        assert _Thing.to_json(normalising)[_ThingKey.LABEL.value] == LABEL.upper()


class TestRequiredDocumentKeys:
    """REQUIRED_INIT_KEYS is checked against the document, not only against the constructor call."""

    def test_a_document_missing_a_required_key_is_refused(self) -> None:
        """Keeps the strictness a model had while it read the key with data['key']."""
        document = _document()
        del document[_ThingKey.LABEL.value]

        with pytest.raises(_ThingFromDataError, match=_ThingKey.LABEL.value):
            _StrictThing.from_data(document)

    def test_a_required_key_holding_none_is_accepted(self) -> None:
        """Presence is the rule, not truthiness - a stored null is the model's own business."""
        assert _StrictThing.from_data(_document(label=None)).label is None

    def test_a_model_declaring_none_accepts_any_document(self) -> None:
        """The check is opt-in, so the models that share the pair today are unaffected."""
        document = _document()
        del document[_ThingKey.LABEL.value]

        assert _Thing.from_data(document).label is None


class TestModelsThatShareNeither:
    """A model without KEYS keeps the behaviour CmdbDAO always had."""

    def test_from_data_is_not_implemented(self) -> None:
        """The message names the class, so the missing implementation is obvious."""
        with pytest.raises(NotImplementedError, match='_KeylessThing'):
            _KeylessThing.from_data({})

    def test_to_json_is_not_implemented(self) -> None:
        """Same for the serialising half."""
        with pytest.raises(NotImplementedError, match='_KeylessThing'):
            _KeylessThing.to_json(SimpleNamespace())

    def test_the_base_class_declares_no_keys(self) -> None:
        """Sharing is opt-in: nothing inherits the pair by accident."""
        assert CmdbDAO.KEYS is None
        assert CmdbDAO.INIT_FROM_DATA_ERROR is None
        assert CmdbDAO.TO_JSON_ERROR is None
