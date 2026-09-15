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
Unit tests for the rule the three membership models share: a stored document is never null

Pure tests: no Mongo, no Flask. CmdbPerson, CmdbPersonGroup and CmdbObjectGroup each write a document
whose optional keys used to be null whenever the payload did not carry them - and each of their
Cerberus schemas types those keys ``string`` / ``list``. The result was a document the API produced and
then refused: a GET followed by an unmodified PUT was answered ``400 Invalid data provided!``, and on
the person-group side a stored ``group_members: null`` made the update route read ``set(None)`` and
answer 500.

The rule is asserted once here, over all three models, because it is one rule and three copies of it
would let the models drift apart again. What is specific to a model is pinned in that model's own
module. ``updater_20260909`` converged the documents written before the fix

Three things are checked per model:

  - a minimal document - only the required keys - survives the round trip through the model AND its own
    schema, which is the exact GET-then-PUT sequence that used to 400
  - an explicit null in any optional key becomes the empty value, since a client may legitimately say
    "no value" and the schemas accept it
  - ``to_json`` emits exactly the key enum, so a key cannot be persisted outside the contract
"""
from inspect import Parameter, signature
from typing import Any, Callable, NamedTuple

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.utils import BaseStrEnum
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError

from cmdb.models.person_model import CmdbPerson, PersonKey, PERSON_LIST_KEYS, PERSON_OPTIONAL_TEXT_KEYS
from cmdb.models.person_group_model import (
    CmdbPersonGroup,
    PersonGroupKey,
    PERSON_GROUP_LIST_KEYS,
    PERSON_GROUP_OPTIONAL_TEXT_KEYS,
)
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectGroupKey, ObjectGroupMode
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4


class _Membership(NamedTuple):
    """One membership model, and everything a shared test needs to address it"""
    model: type[CmdbDAO]
    keys: type[BaseStrEnum]
    minimal_document: dict[str, Any]
    optional_text_keys: tuple[str, ...]
    list_keys: tuple[str, ...]


MEMBERSHIP_MODELS: list[_Membership] = [
    _Membership(
        CmdbPerson,
        PersonKey,
        {
            PersonKey.PUBLIC_ID.value: PUBLIC_ID,
            PersonKey.DISPLAY_NAME.value: 'Ada Lovelace',
            PersonKey.FIRST_NAME.value: 'Ada',
            PersonKey.LAST_NAME.value: 'Lovelace',
        },
        PERSON_OPTIONAL_TEXT_KEYS,
        PERSON_LIST_KEYS,
    ),
    _Membership(
        CmdbPersonGroup,
        PersonGroupKey,
        {
            PersonGroupKey.PUBLIC_ID.value: PUBLIC_ID,
            PersonGroupKey.NAME.value: 'Security officers',
        },
        PERSON_GROUP_OPTIONAL_TEXT_KEYS,
        PERSON_GROUP_LIST_KEYS,
    ),
    _Membership(
        CmdbObjectGroup,
        ObjectGroupKey,
        {
            ObjectGroupKey.PUBLIC_ID.value: PUBLIC_ID,
            ObjectGroupKey.NAME.value: 'Core switches',
            ObjectGroupKey.GROUP_TYPE.value: ObjectGroupMode.STATIC.value,
            ObjectGroupKey.ASSIGNED_IDS.value: [1, 2],
        },
        (),
        (ObjectGroupKey.CATEGORIES.value,),
    ),
]

MODEL_IDS: list[str] = [membership.model.__name__ for membership in MEMBERSHIP_MODELS]


def _stored_document(membership: _Membership, **overrides: Any) -> dict[str, Any]:
    """
    Runs a payload through the model and returns what would be stored

    Args:
        membership (_Membership): The model under test
        **overrides: Keys to add to (or replace in) the minimal document

    Returns:
        dict[str, Any]: The document the model produces
    """
    payload: dict[str, Any] = {**membership.minimal_document, **overrides}

    return membership.model.to_json(membership.model.from_data(payload))


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_a_minimal_document_holds_no_null(membership: _Membership) -> None:
    """
    The keys the payload did not carry are stored as '' / [], never as null

    This is the write half of the defect: the model produced the nulls itself, so a document could
    hold a value its own schema refuses.
    """
    stored: dict[str, Any] = _stored_document(membership)

    assert None not in stored.values()


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_a_stored_document_passes_its_own_schema(membership: _Membership) -> None:
    """
    GET then an unmodified PUT: the exact sequence that used to be answered 400

    The client reads a document and sends it back untouched, which every DataGerry write route
    expects (there is no partial update), so what the model writes has to satisfy what the schema
    accepts.
    """
    validator = Validator(membership.model.SCHEMA)

    assert validator.validate(_stored_document(membership)), validator.errors


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_explicit_nulls_become_empty_values(membership: _Membership) -> None:
    """
    A client saying 'no value' with null is accepted, and null still never reaches the database

    The Angular person form sends email as null when the person has none, which is why the schemas
    are nullable and the coercion lives in the constructor rather than in a route.
    """
    nulled: dict[str, Any] = {
        key: None for key in membership.optional_text_keys + membership.list_keys
    }

    stored: dict[str, Any] = _stored_document(membership, **nulled)

    for key in membership.optional_text_keys:
        assert stored[key] == ''

    for key in membership.list_keys:
        assert stored[key] == []


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_a_null_payload_is_accepted_by_the_schema(membership: _Membership) -> None:
    """The nullable rules and the constructor's coercion are two halves of one contract."""
    validator = Validator(membership.model.SCHEMA)
    payload: dict[str, Any] = {
        **membership.minimal_document,
        **{key: None for key in membership.optional_text_keys + membership.list_keys},
    }
    payload.pop(membership.keys.PUBLIC_ID.value)

    assert validator.validate(payload), validator.errors


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_normalize_document_fills_a_raw_payload(membership: _Membership) -> None:
    """
    The hook the create routes rely on, since they insert the validated payload without a model

    from_data runs it too, so the rule lives in one place for both paths: what a client omitted or
    sent as null is stored as the empty value, not as null.
    """
    payload: dict[str, Any] = dict(membership.minimal_document)
    payload.update({key: None for key in membership.optional_text_keys})

    membership.model.normalize_document(payload)

    for key in membership.optional_text_keys:
        assert payload[key] == ''

    for key in membership.list_keys:
        assert payload[key] == []


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_normalize_document_leaves_a_real_value_alone(membership: _Membership) -> None:
    """Only the missing and the null are filled in; anything else is the schema's business."""
    payload: dict[str, Any] = dict(membership.minimal_document)
    payload.update({key: 'a value' for key in membership.optional_text_keys})
    payload.update({key: [1] for key in membership.list_keys})

    membership.model.normalize_document(payload)

    for key in membership.optional_text_keys:
        assert payload[key] == 'a value'

    for key in membership.list_keys:
        assert payload[key] == [1]


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_to_json_emits_exactly_the_key_enum(membership: _Membership) -> None:
    """
    The key enum is the document contract, in both directions

    A value set on the instance outside the enum cannot reach a response, and a key removed from the
    enum cannot linger in one.
    """
    stored: dict[str, Any] = _stored_document(membership)

    assert set(stored) == {key.value for key in membership.keys}


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_the_key_enum_names_the_constructor_arguments(membership: _Membership) -> None:
    """
    What lets all three share CmdbDAO.from_data: every key is a constructor parameter of that name

    A key added to the enum without the matching parameter would fail on the next read of any
    document, so it is asserted here rather than discovered there.
    """
    # pylint: disable=no-member
    parameters: set[str] = set(membership.model.__init__.__code__.co_varnames)

    assert {key.value for key in membership.keys} <= parameters


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_the_declared_required_keys_are_all_document_keys(membership: _Membership) -> None:
    """A required key outside the enum could never be satisfied by a document."""
    assert set(membership.model.REQUIRED_INIT_KEYS) <= {key.value for key in membership.keys}


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_a_document_missing_a_required_key_is_refused(membership: _Membership) -> None:
    """
    A half-built model whose failure surfaces later is worse than a refusal here

    The same finding the CmdbCategory sweep made: a required key read with .get() produced an
    instance that broke somewhere else, naming neither the document nor the key.
    """
    for required_key in membership.model.REQUIRED_INIT_KEYS:
        incomplete: dict[str, Any] = dict(membership.minimal_document)
        incomplete.pop(required_key)

        with pytest.raises(membership.model.INIT_FROM_DATA_ERROR) as caught:
            membership.model.from_data(incomplete)

        assert required_key in str(caught.value)


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_to_json_refuses_another_models_instance(membership: _Membership) -> None:
    """
    The shared to_json type-checks its instance, so one model cannot serialise as another

    CmdbPerson and CmdbPersonGroup are not structurally identical, but they are handled side by side
    in every membership path, which is exactly where a swapped argument goes unnoticed.
    """
    other: _Membership = next(entry for entry in MEMBERSHIP_MODELS if entry.model is not membership.model)
    foreign_instance: CmdbDAO = other.model.from_data(other.minimal_document)

    with pytest.raises(membership.model.TO_JSON_ERROR):
        membership.model.to_json(foreign_instance)


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_the_constructor_cannot_be_called_positionally(membership: _Membership) -> None:
    """
    CmdbDAO.__new__ reads public_id out of **kwargs and runs first, so a positional call cannot work

    It never could: __new__ raises before __init__ is entered, which is why the signatures are
    declared keyword-only rather than left to look as if positional use were an option.
    """
    builder: Callable[..., Any] = membership.model

    with pytest.raises(RequiredInitKeyNotFoundError):
        builder(PUBLIC_ID)


@pytest.mark.parametrize('membership', MEMBERSHIP_MODELS, ids=MODEL_IDS)
def test_the_constructor_signature_is_keyword_only(membership: _Membership) -> None:
    """Every parameter is keyword-only, so the declaration matches what __new__ enforces."""
    parameters = signature(membership.model.__init__).parameters

    positional = [
        name for name, parameter in parameters.items()
        if name != 'self' and parameter.kind is not Parameter.KEYWORD_ONLY
    ]

    assert not positional
