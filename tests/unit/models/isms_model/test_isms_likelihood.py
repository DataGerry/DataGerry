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
Unit tests for cmdb.models.isms_model.isms_likelihood.IsmsLikelihood

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own - and most of it is about its twin:

  - **``IsmsImpact`` is the structural twin.** Both carry exactly public_id / name /
    calculation_basis / description. Until this model started sharing the type-checked ``to_json``,
    ``IsmsLikelihood.to_json(an_impact)`` returned an impact serialised as a likelihood and said
    nothing. Both directions are pinned below
  - **the two axes must agree on their rules.** They are the two axes of one risk matrix, and they had
    drifted: this scale refused a zero weight while the impact scale allowed it. The cross-model test
    below is what keeps them aligned, and it is the reason the impact schema changed on 2026-09-07
  - what its own schema accepts: a level created without a description round-trips as null, and the
    frontend's edit modal patches that null straight back into the form it saves

``COLLECTION`` is pinned as the document's identity, and the deliberate ABSENCE of ``INDEX_KEYS`` with
it, since the reason (a bounded scale collection) is easy to forget
"""
from types import SimpleNamespace
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.isms_model.isms_impact import IsmsImpact
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.models.isms_model.isms_likelihood import IsmsLikelihood
from cmdb.models.isms_model.isms_likelihood_constants import (
    LIKELIHOOD_REQUIRED_DOCUMENT_KEYS,
    LikelihoodKey,
)
from cmdb.class_schema.isms_model.isms_impact_schema import get_isms_impact_schema
from cmdb.class_schema.isms_model.isms_likelihood_schema import get_isms_likelihood_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_likelihood import (
    IsmsLikelihoodInitError,
    IsmsLikelihoodInitFromDataError,
    IsmsLikelihoodToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 2
NAME: str = 'Rare'
CALCULATION_BASIS: float = 1.0
DESCRIPTION: str = 'Once every few years'


def _document(**overrides: Any) -> dict[str, Any]:
    """
    Builds a complete IsmsLikelihood document

    Args:
        **overrides: Keys to replace in the returned document

    Returns:
        dict[str, Any]: A document carrying every LikelihoodKey
    """
    document: dict[str, Any] = {
        LikelihoodKey.PUBLIC_ID.value: PUBLIC_ID,
        LikelihoodKey.NAME.value: NAME,
        LikelihoodKey.CALCULATION_BASIS.value: CALCULATION_BASIS,
        LikelihoodKey.DESCRIPTION.value: DESCRIPTION,
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
    validator = Validator(get_isms_likelihood_schema(), purge_unknown=True)
    validator.validate(payload)

    return validator


class TestNotMistakenForItsTwin:
    """This is the model the mix-up actually happened to."""

    def test_an_impact_is_refused(self) -> None:
        """
        The regression: this returned an impact serialised as a likelihood, with no complaint

        IsmsImpact had an isinstance guard of its own, so only this direction was broken. The check now
        lives in the shared CmdbDAO.to_json, which is what fixed it for this model and for every other
        one sharing the pair.
        """
        impact = IsmsImpact(public_id = 1, name = 'High', calculation_basis = 3.0)

        with pytest.raises(IsmsLikelihoodToJsonError, match='IsmsImpact'):
            IsmsLikelihood.to_json(impact)

    def test_a_likelihood_is_refused_by_the_impact_model(self) -> None:
        """The other direction, which was already guarded - pinned so both stay symmetric."""
        likelihood = IsmsLikelihood.from_data(_document())

        with pytest.raises(Exception, match='IsmsLikelihood'):
            IsmsImpact.to_json(likelihood)

    def test_a_likelihood_is_accepted(self) -> None:
        """The model's own instances still serialise."""
        assert IsmsLikelihood.to_json(IsmsLikelihood.from_data(_document())) == _document()


class TestTheTwoMatrixAxesAgree:
    """Impact and likelihood are the two axes of one matrix; their rules had drifted apart."""

    def test_the_key_sets_are_identical(self) -> None:
        """Which is exactly why to_json has to type-check its instance."""
        assert {key.value for key in LikelihoodKey} == {key.value for key in ImpactKey}

    def test_both_scales_refuse_a_zero_weight(self) -> None:
        """
        The drift this audit found

        The likelihood schema has always said ``'min': 1e-9``; the impact schema said ``0.0`` until
        2026-09-07, alone among the four layers with an opinion - the two frontend forms both apply
        ``nonZeroValidator`` and the OpenAPI schema documented 1e-9.
        """
        zero_document = {'public_id': 1, 'name': NAME, 'calculation_basis': 0.0}

        assert Validator(get_isms_likelihood_schema()).validate(zero_document) is False
        assert Validator(get_isms_impact_schema()).validate(zero_document) is False

    def test_both_scales_accept_the_same_smallest_weight(self) -> None:
        """A weight just above zero is valid on both axes."""
        smallest_document = {'public_id': 1, 'name': NAME, 'calculation_basis': 1e-9}

        assert Validator(get_isms_likelihood_schema()).validate(smallest_document) is True
        assert Validator(get_isms_impact_schema()).validate(smallest_document) is True

    def test_both_scales_treat_the_description_the_same_way(self) -> None:
        """Optional and nullable on both, because both models emit a null for an unset one."""
        for schema in (get_isms_likelihood_schema(), get_isms_impact_schema()):
            description_rules = schema['description']

            assert description_rules['nullable'] is True
            assert description_rules['required'] is False


class TestKeySetClosure:
    """The model and its schema describe one key set."""

    def test_the_model_shares_the_document_methods(self) -> None:
        """KEYS plus the error types is the declaration; from_data / to_json are inherited."""
        assert IsmsLikelihood.KEYS is LikelihoodKey
        assert IsmsLikelihood.INIT_FROM_DATA_ERROR is IsmsLikelihoodInitFromDataError
        assert IsmsLikelihood.TO_JSON_ERROR is IsmsLikelihoodToJsonError
        assert 'from_data' not in vars(IsmsLikelihood)
        assert 'to_json' not in vars(IsmsLikelihood)

    def test_to_json_emits_exactly_the_declared_keys(self) -> None:
        """A key outside LikelihoodKey would be invisible in every response that uses to_json."""
        payload = IsmsLikelihood.to_json(IsmsLikelihood.from_data(_document()))

        assert set(payload) == {key.value for key in LikelihoodKey}

    def test_the_schema_describes_the_same_key_set(self) -> None:
        """Schema and model cannot drift: purge_unknown drops whatever the schema does not declare."""
        assert set(get_isms_likelihood_schema()) == {key.value for key in LikelihoodKey}


class TestWhatTheModelEmitsIsAcceptedBack:
    """The schema must accept the model's own output, or an unedited level cannot be saved."""

    def test_a_fully_populated_level_round_trips_through_the_schema(self) -> None:
        """The ordinary case, as a baseline."""
        assert _validate(IsmsLikelihood.to_json(IsmsLikelihood.from_data(_document()))).errors == {}

    def test_an_unset_description_is_emitted_as_null_and_accepted(self) -> None:
        """
        The regression: a level created without a description could not be edited

        The list route answers to_json, the edit modal patches that null in unchanged, and the save
        used to come back 400 'null value not allowed'.
        """
        document = _document()
        del document[LikelihoodKey.DESCRIPTION.value]

        payload = IsmsLikelihood.to_json(IsmsLikelihood.from_data(document))

        assert payload[LikelihoodKey.DESCRIPTION.value] is None
        assert _validate(payload).errors == {}


class TestRequiredDocumentKeys:
    """A document without a name or a weight is refused rather than turned into an instance."""

    def test_the_required_keys_are_the_name_and_the_weight(self) -> None:
        """Symmetric with the impact scale; a description stays optional."""
        assert IsmsLikelihood.REQUIRED_INIT_KEYS == LIKELIHOOD_REQUIRED_DOCUMENT_KEYS
        assert set(LIKELIHOOD_REQUIRED_DOCUMENT_KEYS) == {
            LikelihoodKey.NAME.value, LikelihoodKey.CALCULATION_BASIS.value
        }

    @pytest.mark.parametrize('missing_key', LIKELIHOOD_REQUIRED_DOCUMENT_KEYS)
    def test_a_document_missing_one_is_refused(self, missing_key: str) -> None:
        """A tightening: from_data used to read every key with .get and build an instance anyway."""
        document = _document()
        del document[missing_key]

        with pytest.raises(IsmsLikelihoodInitFromDataError, match=missing_key):
            IsmsLikelihood.from_data(document)


class TestDocumentIdentity:
    """COLLECTION is a storage fact, and so is the absence of an index."""

    def test_collection_name(self) -> None:
        """The collection is part of the deployed database layout."""
        assert IsmsLikelihood.COLLECTION == 'isms.likelihood'

    def test_no_indexes_are_declared(self) -> None:
        """
        Deliberate: the likelihood scale is a handful of rows

        The manager does query the collection by calculation_basis for its uniqueness pre-check, but at
        this size the scan is free - and the other ISMS scale entities declare none either.
        """
        assert isinstance(IsmsLikelihood.INDEX_KEYS, list)
        assert not IsmsLikelihood.INDEX_KEYS

    def test_no_date_fields_are_declared(self) -> None:
        """The document holds no date, so it opts out of the CmdbDAO date normalisation."""
        assert isinstance(IsmsLikelihood.DATE_FIELDS, tuple)
        assert not IsmsLikelihood.DATE_FIELDS


class TestKeywordOnlyInit:
    """CmdbDAO.__new__ requires public_id in **kwargs, so the signature must be keyword-only."""

    def test_a_positional_call_is_refused(self) -> None:
        """__new__ runs before __init__ and looks only at **kwargs, so it is what refuses this."""
        with pytest.raises(RequiredInitKeyNotFoundError, match='public_id'):
            # pylint: disable=too-many-function-args,missing-kwoa
            IsmsLikelihood(PUBLIC_ID, NAME, CALCULATION_BASIS)

    def test_a_description_is_optional(self) -> None:
        """It was a required positional until 2026-09-07, unlike the twin's."""
        likelihood = IsmsLikelihood(public_id = PUBLIC_ID, name = NAME,
                                    calculation_basis = CALCULATION_BASIS)

        assert likelihood.get_public_id() == PUBLIC_ID
        assert likelihood.name == NAME
        assert likelihood.calculation_basis == CALCULATION_BASIS
        assert likelihood.description is None


class TestErrorArms:
    """The shared methods raise this model's own error types."""

    def test_init_error_on_an_unusable_public_id(self) -> None:
        """CmdbDAO.__init__ casts public_id with int(), which a None cannot survive."""
        with pytest.raises(IsmsLikelihoodInitError):
            IsmsLikelihood(public_id = None, name = NAME, calculation_basis = CALCULATION_BASIS)

    def test_init_from_data_error_on_an_empty_document(self) -> None:
        """An empty dict fails the required-key check before the constructor is reached."""
        with pytest.raises(IsmsLikelihoodInitFromDataError):
            IsmsLikelihood.from_data({})

    def test_to_json_error_when_the_instance_is_not_one(self) -> None:
        """Anything that is not an IsmsLikelihood is refused by the type check."""
        with pytest.raises(IsmsLikelihoodToJsonError):
            IsmsLikelihood.to_json(SimpleNamespace())
