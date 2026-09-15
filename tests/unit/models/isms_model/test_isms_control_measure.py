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
Unit tests for cmdb.models.isms_model.isms_control_measure.IsmsControlMeasure

Pure tests: no Mongo, no Flask. The model is a flat ten-key document with the ISMS family's
``__init__`` / ``from_data`` / ``to_json`` triple, so what is pinned here is what the triple decides:

  - the round trip is lossless over ``ControlMeasureKey`` and nothing else, and the schema describes
    exactly that key set - the closure that makes a stored-but-invisible key impossible
  - ``is_applicable`` is normalised to a boolean, because the Statement of Applicability has two
    answers and the schema still accepts a null on write
  - each failure converts into the model's own error type. Those three ``except`` arms were the whole
    coverage gap of this file before 2026-09-07; they now live once on ``CmdbDAO``, and this model
    declares ``KEYS`` plus its two error types instead of carrying its own copy of the triple
    (tests/unit/models/test_cmdb_dao_shared_document.py owns the shared machinery)
  - the signature is keyword-only, which it has to be: ``CmdbDAO.__new__`` looks for ``public_id`` in
    ``**kwargs`` and runs before ``__init__``, so a positional call has never been able to work. It
    still raises ``RequiredInitKeyNotFoundError: A required InitKey is missing: public_id!`` - what the
    keyword-only signature changed is that the claim is now true, where before the signature accepted
    the positional call that the message then blamed on a missing argument

``INDEX_KEYS`` / ``COLLECTION`` are pinned as the document's identity, since a change there needs a
migration rather than a test edit
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.models.isms_model.isms_control_measure import IsmsControlMeasure
from cmdb.models.isms_model.isms_control_measure_constants import (
    CONTROL_MEASURE_IMPORT_KEYS,
    ControlMeasureKey,
)
from cmdb.models.isms_model.control_measure_type_enum import ControlMeasureType
from cmdb.class_schema.isms_model.isms_control_measure_schema import get_isms_control_measure_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_control_measure import (
    IsmsControlMeasureInitError,
    IsmsControlMeasureInitFromDataError,
    IsmsControlMeasureToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4711
TITLE: str = 'Access control policy'
SOURCE_ID: int = 12
IMPLEMENTATION_STATE_ID: int = 34
IDENTIFIER: str = 'A.5.15'
CHAPTER: str = '5.15'
DESCRIPTION: str = 'Rules for access to information'
REASON: str = 'Required by the ISMS scope'


def _document(**overrides: Any) -> dict[str, Any]:
    """
    Builds a complete IsmsControlMeasure document

    Args:
        **overrides: Keys to replace in the returned document

    Returns:
        dict[str, Any]: A document carrying every ControlMeasureKey
    """
    document: dict[str, Any] = {
        ControlMeasureKey.PUBLIC_ID.value: PUBLIC_ID,
        ControlMeasureKey.TITLE.value: TITLE,
        ControlMeasureKey.CONTROL_MEASURE_TYPE.value: ControlMeasureType.CONTROL.value,
        ControlMeasureKey.SOURCE.value: SOURCE_ID,
        ControlMeasureKey.IMPLEMENTATION_STATE.value: IMPLEMENTATION_STATE_ID,
        ControlMeasureKey.IDENTIFIER.value: IDENTIFIER,
        ControlMeasureKey.CHAPTER.value: CHAPTER,
        ControlMeasureKey.DESCRIPTION.value: DESCRIPTION,
        ControlMeasureKey.IS_APPLICABLE.value: True,
        ControlMeasureKey.REASON.value: REASON,
    }
    document.update(overrides)

    return document


class TestKeySetClosure:
    """The model, its schema and the importer's column list describe one key set."""

    def test_the_model_shares_the_document_methods(self) -> None:
        """KEYS plus the two error types is the whole declaration; from_data / to_json are inherited."""
        assert IsmsControlMeasure.KEYS is ControlMeasureKey
        assert IsmsControlMeasure.INIT_FROM_DATA_ERROR is IsmsControlMeasureInitFromDataError
        assert IsmsControlMeasure.TO_JSON_ERROR is IsmsControlMeasureToJsonError
        assert 'from_data' not in vars(IsmsControlMeasure)
        assert 'to_json' not in vars(IsmsControlMeasure)

    def test_to_json_emits_exactly_the_declared_keys(self) -> None:
        """A key outside ControlMeasureKey would be invisible in every response that uses to_json."""
        payload = IsmsControlMeasure.to_json(IsmsControlMeasure.from_data(_document()))

        assert set(payload) == {key.value for key in ControlMeasureKey}

    def test_the_schema_describes_the_same_key_set(self) -> None:
        """Schema and model cannot drift: purge_unknown drops whatever the schema does not declare."""
        assert set(get_isms_control_measure_schema()) == {key.value for key in ControlMeasureKey}

    def test_the_import_columns_are_the_document_keys_without_public_id(self) -> None:
        """public_id is server-owned, so a CSV carries every other key - and no key of its own."""
        assert set(CONTROL_MEASURE_IMPORT_KEYS) == {key.value for key in ControlMeasureKey} - {
            ControlMeasureKey.PUBLIC_ID.value
        }

    def test_the_round_trip_is_lossless(self) -> None:
        """from_data -> to_json returns the document it was given."""
        document = _document()

        assert IsmsControlMeasure.to_json(IsmsControlMeasure.from_data(document)) == document


class TestDocumentIdentity:
    """COLLECTION and INDEX_KEYS are storage facts, not implementation details."""

    def test_collection_name(self) -> None:
        """The collection is part of the deployed database layout."""
        assert IsmsControlMeasure.COLLECTION == 'isms.controlMeasure'

    def test_the_only_declared_index_is_the_control_measure_type(self) -> None:
        """Index changes need a migration (reconciliation is additive), so the set is pinned."""
        assert [index['name'] for index in IsmsControlMeasure.INDEX_KEYS] == ['control_measure_type']
        assert IsmsControlMeasure.INDEX_KEYS[0]['keys'] == [
            (ControlMeasureKey.CONTROL_MEASURE_TYPE.value, IsmsControlMeasure.DAO_ASCENDING)
        ]
        assert IsmsControlMeasure.INDEX_KEYS[0]['unique'] is False

    def test_no_date_fields_are_declared(self) -> None:
        """The document holds no date, so it opts out of the CmdbDAO date normalisation."""
        assert isinstance(IsmsControlMeasure.DATE_FIELDS, tuple)
        assert not IsmsControlMeasure.DATE_FIELDS


class TestIsApplicableNormalisation:
    """The Statement of Applicability answer has two states, never three."""

    @pytest.mark.parametrize('stored', [None, False, 0, ''])
    def test_a_null_or_falsy_value_reads_as_false(self, stored: Any) -> None:
        """A null renders as an empty cell in the SoA report, where a False renders as 'No'."""
        measure = IsmsControlMeasure.from_data(_document(is_applicable=stored))

        assert measure.is_applicable is False

    def test_an_absent_key_reads_as_false(self) -> None:
        """A document written before the field existed answers 'not applicable', not 'unknown'."""
        document = _document()
        del document[ControlMeasureKey.IS_APPLICABLE.value]

        assert IsmsControlMeasure.from_data(document).is_applicable is False

    def test_true_survives(self) -> None:
        """Normalisation must not flatten the one answer that carries an obligation."""
        assert IsmsControlMeasure.from_data(_document(is_applicable=True)).is_applicable is True

    def test_the_normalize_document_hook_edits_the_given_dict(self) -> None:
        """The hook the shared from_data calls; the SoA report calls it on raw documents directly."""
        document = _document(is_applicable=None)

        IsmsControlMeasure.normalize_document(document)

        assert document[ControlMeasureKey.IS_APPLICABLE.value] is False

    def test_normalize_is_applicable_edits_the_given_dict(self) -> None:
        """The insert route writes the validated payload straight to the collection."""
        payload = _document(is_applicable=None)

        result = IsmsControlMeasure.normalize_is_applicable(payload)

        assert result is payload
        assert payload[ControlMeasureKey.IS_APPLICABLE.value] is False

    def test_to_json_reports_the_normalised_value(self) -> None:
        """The list route answers to_json(instance), so the wire value is a boolean too."""
        payload = IsmsControlMeasure.to_json(IsmsControlMeasure.from_data(_document(is_applicable=None)))

        assert payload[ControlMeasureKey.IS_APPLICABLE.value] is False


class TestKeywordOnlyInit:
    """CmdbDAO.__new__ requires public_id in **kwargs, so the signature must be keyword-only."""

    def test_a_positional_call_is_refused(self) -> None:
        """
        CmdbDAO.__new__ runs before __init__ and looks only at **kwargs, so it - not Python's argument
        binding - is what refuses this, and the error type is the same as before the signature became
        keyword-only. What changed is that the message is now true: with no positional parameters to
        bind to, public_id really was not given
        """
        with pytest.raises(RequiredInitKeyNotFoundError, match='public_id'):
            # pylint: disable=too-many-function-args,missing-kwoa
            IsmsControlMeasure(PUBLIC_ID, TITLE, ControlMeasureType.CONTROL.value, SOURCE_ID,
                               IMPLEMENTATION_STATE_ID)

    def test_the_keyword_call_populates_every_attribute(self) -> None:
        """The optional fields keep their documented defaults."""
        measure = IsmsControlMeasure(
            public_id = PUBLIC_ID,
            title = TITLE,
            control_measure_type = ControlMeasureType.CONTROL.value,
            source = SOURCE_ID,
            implementation_state = IMPLEMENTATION_STATE_ID,
        )

        assert measure.get_public_id() == PUBLIC_ID
        assert measure.title == TITLE
        assert measure.identifier is None
        assert measure.chapter is None
        assert measure.description is None
        assert measure.reason is None
        assert measure.is_applicable is False


class TestErrorArms:
    """Each of the three except arms converts its failure into the model's own error type."""

    def test_init_error_on_an_unusable_public_id(self) -> None:
        """CmdbDAO.__init__ casts public_id with int(), which a None cannot survive."""
        with pytest.raises(IsmsControlMeasureInitError):
            IsmsControlMeasure(
                public_id = None,
                title = TITLE,
                control_measure_type = ControlMeasureType.CONTROL.value,
                source = SOURCE_ID,
                implementation_state = IMPLEMENTATION_STATE_ID,
            )

    def test_init_from_data_error_on_an_empty_document(self) -> None:
        """An empty dict has no public_id, so the inner InitError is rewrapped by from_data."""
        with pytest.raises(IsmsControlMeasureInitFromDataError):
            IsmsControlMeasure.from_data({})

    def test_to_json_error_when_the_instance_is_not_one(self) -> None:
        """to_json reads get_public_id() plus nine attributes; anything missing is a ToJsonError."""
        with pytest.raises(IsmsControlMeasureToJsonError):
            IsmsControlMeasure.to_json(SimpleNamespace())
