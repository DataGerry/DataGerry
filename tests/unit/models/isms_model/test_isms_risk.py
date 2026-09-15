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
Unit tests for cmdb.models.isms_model.isms_risk.IsmsRisk

Pure tests: no Mongo, no Flask. The model now declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own:

  - **what its own schema accepts.** An unset identifier, consequences or description round-trips as
    null, and the frontend patches that null back into the form it later saves - so ``to_json``'s output
    is validated against ``SCHEMA`` here. It used to fail with 'null value not allowed', which made an
    imported risk unsaveable from the UI
  - **the three reference lists are never null**, whether the key is missing, null or empty - the
    constructor coerces all three, where it used to coerce only two
  - ``risk_type`` is pinned to RiskType by the schema, not by the route that used to re-check it
  - the index set, ``protection_goals`` included: without it, every ProtectionGoal delete scanned this
    collection

``COLLECTION`` / ``INDEX_KEYS`` are pinned as the document's identity, since a change there needs a
migration rather than a test edit
"""
from types import SimpleNamespace
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.models.isms_model.isms_risk_constants import RISK_IMPORT_KEYS, RiskKey
from cmdb.models.isms_model.risk_type_enum import RiskType
from cmdb.class_schema.isms_model.isms_risk_schema import get_isms_risk_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_risk import (
    IsmsRiskInitError,
    IsmsRiskInitFromDataError,
    IsmsRiskToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 8123
NAME: str = 'Unauthorised access to the CMDB'
CATEGORY_ID: int = 9
IDENTIFIER: str = 'R-14'
CONSEQUENCES: str = 'Loss of confidentiality'
DESCRIPTION: str = 'An attacker reaches the asset inventory'

REFERENCE_LIST_KEYS: tuple[str, ...] = (
    RiskKey.PROTECTION_GOALS.value,
    RiskKey.THREATS.value,
    RiskKey.VULNERABILITIES.value,
)


def _document(**overrides: Any) -> dict[str, Any]:
    """
    Builds a complete IsmsRisk document of the THREAT_X_VULNERABILITY type

    Args:
        **overrides: Keys to replace in the returned document

    Returns:
        dict[str, Any]: A document carrying every RiskKey
    """
    document: dict[str, Any] = {
        RiskKey.PUBLIC_ID.value: PUBLIC_ID,
        RiskKey.NAME.value: NAME,
        RiskKey.RISK_TYPE.value: RiskType.THREAT_X_VULNERABILITY.value,
        RiskKey.PROTECTION_GOALS.value: [1, 2],
        RiskKey.THREATS.value: [3],
        RiskKey.VULNERABILITIES.value: [4],
        RiskKey.CATEGORY_ID.value: CATEGORY_ID,
        RiskKey.IDENTIFIER.value: IDENTIFIER,
        RiskKey.CONSEQUENCES.value: CONSEQUENCES,
        RiskKey.DESCRIPTION.value: DESCRIPTION,
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
    validator = Validator(get_isms_risk_schema(), purge_unknown=True)
    validator.validate(payload)

    return validator


class TestKeySetClosure:
    """The model, its schema and the importer's column list describe one key set."""

    def test_the_model_shares_the_document_methods(self) -> None:
        """KEYS plus the two error types is the whole declaration; from_data / to_json are inherited."""
        assert IsmsRisk.KEYS is RiskKey
        assert IsmsRisk.INIT_FROM_DATA_ERROR is IsmsRiskInitFromDataError
        assert IsmsRisk.TO_JSON_ERROR is IsmsRiskToJsonError
        assert 'from_data' not in vars(IsmsRisk)
        assert 'to_json' not in vars(IsmsRisk)

    def test_to_json_emits_exactly_the_declared_keys(self) -> None:
        """A key outside RiskKey would be invisible in every response that uses to_json."""
        payload = IsmsRisk.to_json(IsmsRisk.from_data(_document()))

        assert set(payload) == {key.value for key in RiskKey}

    def test_the_schema_describes_the_same_key_set(self) -> None:
        """Schema and model cannot drift: purge_unknown drops whatever the schema does not declare."""
        assert set(get_isms_risk_schema()) == {key.value for key in RiskKey}

    def test_the_import_columns_omit_the_two_keys_a_csv_has_no_column_for(self) -> None:
        """public_id is server-owned; a category is given in the UI after the import."""
        assert set(RISK_IMPORT_KEYS) == {key.value for key in RiskKey} - {
            RiskKey.PUBLIC_ID.value, RiskKey.CATEGORY_ID.value
        }

    def test_the_round_trip_is_lossless(self) -> None:
        """from_data -> to_json returns the document it was given."""
        document = _document()

        assert IsmsRisk.to_json(IsmsRisk.from_data(document)) == document


class TestWhatTheModelEmitsIsAcceptedBack:
    """The schema must accept the model's own output, or an unedited risk cannot be saved."""

    def test_a_fully_populated_risk_round_trips_through_the_schema(self) -> None:
        """The ordinary case, as a baseline for the ones below."""
        assert _validate(IsmsRisk.to_json(IsmsRisk.from_data(_document()))).errors == {}

    @pytest.mark.parametrize('unset_key', [
        RiskKey.IDENTIFIER.value,
        RiskKey.CONSEQUENCES.value,
        RiskKey.DESCRIPTION.value,
    ])
    def test_an_unset_text_field_is_emitted_as_null_and_accepted(self, unset_key: str) -> None:
        """
        The regression that made an imported risk unsaveable

        The ISMS importer stores None for a blank cell, to_json emits that null, the frontend patches
        it into the form unchanged, and the schema answered 'null value not allowed' on save.
        """
        document = _document()
        del document[unset_key]

        payload = IsmsRisk.to_json(IsmsRisk.from_data(document))

        assert payload[unset_key] is None
        assert _validate(payload).errors == {}

    def test_an_unknown_risk_type_is_refused_by_the_schema_itself(self) -> None:
        """It used to pass validation and be caught by a re-check in the insert and update routes."""
        errors = _validate(_document(risk_type='NOT_A_RISK_TYPE')).errors

        assert RiskKey.RISK_TYPE.value in errors

    @pytest.mark.parametrize('risk_type', [risk_type.value for risk_type in RiskType])
    def test_every_risk_type_value_is_allowed(self, risk_type: str) -> None:
        """The allowed list is built from the enum, so the two cannot drift."""
        assert _validate(_document(risk_type=risk_type)).errors == {}


class TestReferenceListsAreAlwaysLists:
    """A missing key, a stored null and an empty list all mean 'nothing referenced'."""

    @pytest.mark.parametrize('list_key', REFERENCE_LIST_KEYS)
    def test_a_missing_key_reads_as_an_empty_list(self, list_key: str) -> None:
        """protection_goals was the odd one out - it used to read as None."""
        document = _document()
        del document[list_key]

        assert getattr(IsmsRisk.from_data(document), list_key) == []

    @pytest.mark.parametrize('list_key', REFERENCE_LIST_KEYS)
    def test_a_stored_null_reads_as_an_empty_list(self, list_key: str) -> None:
        """The report $lookup stages and the frontend's `|| []` guards both assume a list."""
        assert getattr(IsmsRisk.from_data(_document(**{list_key: None})), list_key) == []

    @pytest.mark.parametrize('list_key', REFERENCE_LIST_KEYS)
    def test_the_emitted_value_is_a_list_too(self, list_key: str) -> None:
        """to_json reports what the constructor coerced, so no response carries a null list."""
        document = _document()
        del document[list_key]

        assert IsmsRisk.to_json(IsmsRisk.from_data(document))[list_key] == []


class TestDocumentIdentity:
    """COLLECTION and INDEX_KEYS are storage facts, not implementation details."""

    def test_collection_name(self) -> None:
        """The collection is part of the deployed database layout."""
        assert IsmsRisk.COLLECTION == 'isms.risk'

    def test_the_declared_indexes(self) -> None:
        """
        Index changes need a migration (reconciliation is additive), so the set is pinned

        protection_goals is the one added on 2026-09-07: delete_isms_item_if_unused_by_risk asks this
        collection whether a risk still references a ProtectionGoal, exactly as it does for the other
        two lists, and that question was a collection scan.
        """
        assert [index['name'] for index in IsmsRisk.INDEX_KEYS] == [
            RiskKey.RISK_TYPE.value,
            RiskKey.PROTECTION_GOALS.value,
            RiskKey.THREATS.value,
            RiskKey.VULNERABILITIES.value,
            RiskKey.IDENTIFIER.value,
        ]

    @pytest.mark.parametrize('list_key', REFERENCE_LIST_KEYS)
    def test_every_reference_list_the_delete_guards_query_is_indexed(self, list_key: str) -> None:
        """The three guards differ only in the field, so all three fields must be indexed."""
        indexed = {index['keys'][0][0] for index in IsmsRisk.INDEX_KEYS}

        assert list_key in indexed

    def test_no_date_fields_are_declared(self) -> None:
        """The document holds no date, so it opts out of the CmdbDAO date normalisation."""
        assert isinstance(IsmsRisk.DATE_FIELDS, tuple)
        assert not IsmsRisk.DATE_FIELDS


class TestKeywordOnlyInit:
    """CmdbDAO.__new__ requires public_id in **kwargs, so the signature must be keyword-only."""

    def test_a_positional_call_is_refused(self) -> None:
        """__new__ runs before __init__ and looks only at **kwargs, so it is what refuses this."""
        with pytest.raises(RequiredInitKeyNotFoundError, match='public_id'):
            # pylint: disable=too-many-function-args,missing-kwoa
            IsmsRisk(PUBLIC_ID, NAME, RiskType.THREAT.value)

    def test_the_keyword_call_populates_every_attribute(self) -> None:
        """The optional fields keep their documented defaults."""
        risk = IsmsRisk(public_id = PUBLIC_ID, name = NAME, risk_type = RiskType.EVENT.value)

        assert risk.get_public_id() == PUBLIC_ID
        assert risk.name == NAME
        assert risk.protection_goals == []
        assert risk.threats == []
        assert risk.vulnerabilities == []
        assert risk.category_id is None
        assert risk.identifier is None
        assert risk.consequences is None
        assert risk.description is None


class TestErrorArms:
    """The shared methods raise this model's own error types."""

    def test_init_error_on_an_unusable_public_id(self) -> None:
        """CmdbDAO.__init__ casts public_id with int(), which a None cannot survive."""
        with pytest.raises(IsmsRiskInitError):
            IsmsRisk(public_id = None, name = NAME, risk_type = RiskType.THREAT.value)

    def test_init_from_data_error_on_an_empty_document(self) -> None:
        """An empty dict has no public_id, so the inner InitError is rewrapped."""
        with pytest.raises(IsmsRiskInitFromDataError):
            IsmsRisk.from_data({})

    def test_to_json_error_when_the_instance_is_not_one(self) -> None:
        """to_json reads get_public_id() plus nine attributes; anything missing is a ToJsonError."""
        with pytest.raises(IsmsRiskToJsonError):
            IsmsRisk.to_json(SimpleNamespace())
