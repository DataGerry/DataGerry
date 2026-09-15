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
Unit tests for cmdb.models.isms_model.isms_impact.IsmsImpact

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own - and this one had two behaviours worth keeping that a
naive migration would have dropped:

  - **``IsmsLikelihood`` is its structural twin.** Both carry exactly public_id / name /
    calculation_basis / description, so one serialises cleanly as the other. This model used to be the
    only ISMS entity with an isinstance guard in its own ``to_json``; the check now lives in the shared
    implementation, and the test below is the reason it had to
  - **it read its required keys with ``data['key']``**, so a document missing one was an error rather
    than an instance holding None. ``REQUIRED_INIT_KEYS`` is what keeps that after the migration

Plus what its own schema accepts: an impact created without a description round-trips as null, and the
frontend's edit modal patches that null straight back into the form it saves - which the schema used to
answer with 'null value not allowed'.

``COLLECTION`` is pinned as the document's identity, and the deliberate ABSENCE of ``INDEX_KEYS`` with
it, since the reason (a bounded scale collection) is easy to forget
"""
from types import SimpleNamespace
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.isms_model.isms_impact import IsmsImpact
from cmdb.models.isms_model.isms_impact_constants import IMPACT_REQUIRED_DOCUMENT_KEYS, ImpactKey
from cmdb.models.isms_model.isms_likelihood import IsmsLikelihood
from cmdb.class_schema.isms_model.isms_impact_schema import get_isms_impact_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_impact import (
    IsmsImpactInitError,
    IsmsImpactInitFromDataError,
    IsmsImpactToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 3
NAME: str = 'High'
CALCULATION_BASIS: float = 3.0
DESCRIPTION: str = 'Serious damage to the organisation'


def _document(**overrides: Any) -> dict[str, Any]:
    """
    Builds a complete IsmsImpact document

    Args:
        **overrides: Keys to replace in the returned document

    Returns:
        dict[str, Any]: A document carrying every ImpactKey
    """
    document: dict[str, Any] = {
        ImpactKey.PUBLIC_ID.value: PUBLIC_ID,
        ImpactKey.NAME.value: NAME,
        ImpactKey.CALCULATION_BASIS.value: CALCULATION_BASIS,
        ImpactKey.DESCRIPTION.value: DESCRIPTION,
    }
    document.update(overrides)

    return document


def _validate(payload: dict[str, Any]) -> Validator:
    """
    Validates a payload against the model's own schema

    Args:
        payload (dict[str, Any]): The payload to validate

    Returns:
        Validator: The validator, already run - read ``.errors`` for the failure
    """
    validator = Validator(get_isms_impact_schema(), purge_unknown=True)
    validator.validate(payload)

    return validator


class TestNotMistakenForItsTwin:
    """IsmsImpact and IsmsLikelihood carry the same four keys, so the type check is load-bearing."""

    def test_a_likelihood_is_refused(self) -> None:
        """
        Without the check this returns a likelihood serialised as an impact, and says nothing

        The check used to live in this model's own to_json and is now in CmdbDAO's, so every model
        sharing the pair is protected - which is also why this test lives here, on the model that
        needed it first.
        """
        likelihood = IsmsLikelihood(public_id = 9, name = 'Rare', calculation_basis = 1.0,
                                    description = 'Unlikely')

        with pytest.raises(IsmsImpactToJsonError, match='IsmsLikelihood'):
            IsmsImpact.to_json(likelihood)

    def test_an_impact_is_accepted(self) -> None:
        """The other half of the check: the model's own instances still serialise."""
        assert IsmsImpact.to_json(IsmsImpact.from_data(_document())) == _document()


class TestKeySetClosure:
    """The model and its schema describe one key set."""

    def test_the_model_shares_the_document_methods(self) -> None:
        """KEYS plus the error types is the declaration; from_data / to_json are inherited."""
        assert IsmsImpact.KEYS is ImpactKey
        assert IsmsImpact.INIT_FROM_DATA_ERROR is IsmsImpactInitFromDataError
        assert IsmsImpact.TO_JSON_ERROR is IsmsImpactToJsonError
        assert 'from_data' not in vars(IsmsImpact)
        assert 'to_json' not in vars(IsmsImpact)

    def test_to_json_emits_exactly_the_declared_keys(self) -> None:
        """A key outside ImpactKey would be invisible in every response that uses to_json."""
        payload = IsmsImpact.to_json(IsmsImpact.from_data(_document()))

        assert set(payload) == {key.value for key in ImpactKey}

    def test_the_schema_describes_the_same_key_set(self) -> None:
        """Schema and model cannot drift: purge_unknown drops whatever the schema does not declare."""
        assert set(get_isms_impact_schema()) == {key.value for key in ImpactKey}


class TestWhatTheModelEmitsIsAcceptedBack:
    """The schema must accept the model's own output, or an unedited impact cannot be saved."""

    def test_a_fully_populated_impact_round_trips_through_the_schema(self) -> None:
        """The ordinary case, as a baseline."""
        assert _validate(IsmsImpact.to_json(IsmsImpact.from_data(_document()))).errors == {}

    def test_an_unset_description_is_emitted_as_null_and_accepted(self) -> None:
        """
        The regression: an impact created through the API without a description could not be edited

        The list route answers to_json, the edit modal patches that null in unchanged, and the save
        used to come back 400 'null value not allowed'.
        """
        document = _document()
        del document[ImpactKey.DESCRIPTION.value]

        payload = IsmsImpact.to_json(IsmsImpact.from_data(document))

        assert payload[ImpactKey.DESCRIPTION.value] is None
        assert _validate(payload).errors == {}


class TestCalculationBasisIsANumber:
    """It is the weight the risk matrix multiplies, not a label."""

    def test_the_schema_refuses_a_string(self) -> None:
        """The model annotated it `str` until 2026-09-07 - the only claim of that anywhere."""
        assert ImpactKey.CALCULATION_BASIS.value in _validate(_document(calculation_basis='3')).errors

    def test_the_schema_refuses_a_negative_weight(self) -> None:
        """A negative impact has no meaning in the matrix."""
        assert ImpactKey.CALCULATION_BASIS.value in _validate(_document(calculation_basis=-1.0)).errors

    def test_zero_is_refused(self) -> None:
        """
        A zero-weight level would flatten every risk that uses it

        This schema accepted 0.0 until 2026-09-07 - alone among the four layers with an opinion: the
        likelihood scale (the other axis of the same matrix) has always said ``'min': 1e-9``, both
        frontend forms apply ``nonZeroValidator``, and the OpenAPI schema documented 1e-9. The
        ``isms_likelihood.py`` audit is what identified which layer was wrong.
        """
        assert ImpactKey.CALCULATION_BASIS.value in _validate(_document(calculation_basis=0.0)).errors

    def test_the_smallest_positive_weight_is_allowed(self) -> None:
        """The bound is 'greater than zero', not 'at least one'."""
        assert _validate(_document(calculation_basis=1e-9)).errors == {}


class TestRequiredDocumentKeys:
    """The strictness that data['key'] used to provide, kept across the migration."""

    def test_the_required_keys_are_the_name_and_the_weight(self) -> None:
        """public_id is CmdbDAO's own business; a description is optional by design."""
        assert IsmsImpact.REQUIRED_INIT_KEYS == IMPACT_REQUIRED_DOCUMENT_KEYS
        assert set(IMPACT_REQUIRED_DOCUMENT_KEYS) == {
            ImpactKey.NAME.value, ImpactKey.CALCULATION_BASIS.value
        }

    @pytest.mark.parametrize('missing_key', IMPACT_REQUIRED_DOCUMENT_KEYS)
    def test_a_document_missing_one_is_refused(self, missing_key: str) -> None:
        """It used to raise a KeyError from data['key']; now the message names what is missing."""
        document = _document()
        del document[missing_key]

        with pytest.raises(IsmsImpactInitFromDataError, match=missing_key):
            IsmsImpact.from_data(document)

    def test_a_document_without_a_description_is_fine(self) -> None:
        """The optional key stays optional."""
        document = _document()
        del document[ImpactKey.DESCRIPTION.value]

        assert IsmsImpact.from_data(document).description is None


class TestDocumentIdentity:
    """COLLECTION is a storage fact, and so is the absence of an index."""

    def test_collection_name(self) -> None:
        """The collection is part of the deployed database layout."""
        assert IsmsImpact.COLLECTION == 'isms.impact'

    def test_no_indexes_are_declared(self) -> None:
        """
        Deliberate: the impact scale is a handful of rows

        The frontend's table sorts on calculation_basis server-side, but the whole collection is
        preloaded in one query by load_impact_calculation_basis, so an index would buy nothing. The
        other ISMS scale entities declare none either.
        """
        assert isinstance(IsmsImpact.INDEX_KEYS, list)
        assert not IsmsImpact.INDEX_KEYS

    def test_no_date_fields_are_declared(self) -> None:
        """The document holds no date, so it opts out of the CmdbDAO date normalisation."""
        assert isinstance(IsmsImpact.DATE_FIELDS, tuple)
        assert not IsmsImpact.DATE_FIELDS


class TestKeywordOnlyInit:
    """CmdbDAO.__new__ requires public_id in **kwargs, so the signature must be keyword-only."""

    def test_a_positional_call_is_refused(self) -> None:
        """__new__ runs before __init__ and looks only at **kwargs, so it is what refuses this."""
        with pytest.raises(RequiredInitKeyNotFoundError, match='public_id'):
            # pylint: disable=too-many-function-args,missing-kwoa
            IsmsImpact(PUBLIC_ID, NAME, CALCULATION_BASIS)

    def test_the_keyword_call_populates_every_attribute(self) -> None:
        """A description is the only optional field."""
        impact = IsmsImpact(public_id = PUBLIC_ID, name = NAME, calculation_basis = CALCULATION_BASIS)

        assert impact.get_public_id() == PUBLIC_ID
        assert impact.name == NAME
        assert impact.calculation_basis == CALCULATION_BASIS
        assert impact.description is None


class TestErrorArms:
    """The shared methods raise this model's own error types."""

    def test_init_error_on_an_unusable_public_id(self) -> None:
        """CmdbDAO.__init__ casts public_id with int(), which a None cannot survive."""
        with pytest.raises(IsmsImpactInitError):
            IsmsImpact(public_id = None, name = NAME, calculation_basis = CALCULATION_BASIS)

    def test_init_from_data_error_on_an_empty_document(self) -> None:
        """An empty dict fails the required-key check before the constructor is reached."""
        with pytest.raises(IsmsImpactInitFromDataError):
            IsmsImpact.from_data({})

    def test_to_json_error_when_the_instance_is_not_one(self) -> None:
        """Anything that is not an IsmsImpact is refused by the type check."""
        with pytest.raises(IsmsImpactToJsonError):
            IsmsImpact.to_json(SimpleNamespace())
