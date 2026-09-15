# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.models.isms_model.isms_risk_assessment

Pins the four properties of an IsmsRiskAssessment that other code depends on and that nothing else
would notice breaking:

* its date fields are real dates in the document and the ``{'$date': ...}`` wrapper on the wire - the
  storage half is what lets MongoDB sort and range-filter them, the wire half is what keeps the
  frontend working
* its key set is closed: ``from_data`` / ``to_json`` round-trip exactly ``RiskAssessmentKey``, which
  the read routes rely on because they answer with ``to_json(from_data(document))``, and which the
  Cerberus schema must therefore agree with key for key
* an unreadable date is refused rather than guessed
* the fields the CmdbPerson delete-cascade filters on are indexed

Pure tests: no Mongo, no Flask
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.class_schema.isms_model.isms_risk_assessment_schema import get_isms_risk_assessment_schema
from cmdb.database.json_codec import default
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import (
    CONTROL_MEASURE_ASSIGNMENTS_KEY,
    RISK_ASSESSMENT_DATE_KEYS,
    RiskAssessmentKey,
)
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.isms_model.treatment_option_enum import TreatmentOption
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_risk_assessment import (
    IsmsRiskAssessmentInitError,
    IsmsRiskAssessmentInitFromDataError,
    IsmsRiskAssessmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

RISK_ASSESSMENT_ID: int = 42
RISK_ID: int = 7
OBJECT_ID: int = 8
PERSON_ID: int = 9

# The instant used throughout, in both of its shapes: 2020-09-13 12:26:40 UTC
STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)

# The fields the CmdbPerson delete-cascade filters on (PersonsManager.remove_person_from_risk_assessments):
# one filtered update per entry, so each of them needs an index of its own
PERSON_CASCADE_FIELDS: tuple[RiskAssessmentKey, ...] = (
    RiskAssessmentKey.RISK_ASSESSOR_ID,
    RiskAssessmentKey.RISK_OWNER_ID,
    RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE,
    RiskAssessmentKey.AUDITOR_ID,
    RiskAssessmentKey.AUDITOR_ID_REF_TYPE,
    RiskAssessmentKey.INTERVIEWED_PERSONS,
)


def _assessment_data(**overrides: Any) -> dict[str, Any]:
    """Builds a complete IsmsRiskAssessment document, overridable per test"""
    data: dict[str, Any] = {
        RiskAssessmentKey.PUBLIC_ID.value: RISK_ASSESSMENT_ID,
        RiskAssessmentKey.RISK_ID.value: RISK_ID,
        RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: ObjectReferenceType.OBJECT.value,
        RiskAssessmentKey.OBJECT_ID.value: OBJECT_ID,
        RiskAssessmentKey.RISK_CALCULATION_BEFORE.value: {'impacts': []},
        RiskAssessmentKey.RISK_ASSESSOR_ID.value: PERSON_ID,
        RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value: PersonReferenceType.PERSON.value,
        RiskAssessmentKey.RISK_OWNER_ID.value: PERSON_ID,
        RiskAssessmentKey.INTERVIEWED_PERSONS.value: [PERSON_ID],
        RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {'$date': STAMP_MILLIS},
        RiskAssessmentKey.ADDITIONAL_INFO.value: 'note',
        RiskAssessmentKey.RISK_TREATMENT_OPTION.value: TreatmentOption.REDUCE.value,
        RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value: PersonReferenceType.PERSON.value,
        RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value: PERSON_ID,
        RiskAssessmentKey.RISK_TREATMENT_DESCRIPTION.value: 'treat it',
        RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: None,
        RiskAssessmentKey.IMPLEMENTATION_STATUS.value: None,
        RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value: None,
        RiskAssessmentKey.REQUIRED_RESOURCES.value: None,
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value: 0.0,
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION_CURRENCY.value: None,
        RiskAssessmentKey.PRIORITY.value: Priority.LOW.value,
        RiskAssessmentKey.RISK_CALCULATION_AFTER.value: {},
        RiskAssessmentKey.AUDIT_DONE_DATE.value: None,
        RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value: PersonReferenceType.PERSON.value,
        RiskAssessmentKey.AUDITOR_ID.value: None,
        RiskAssessmentKey.AUDIT_RESULT.value: None,
    }
    data.update(overrides)

    return data


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     date fields                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDateFields:
    """The four dates are stored as real dates, whichever shape they arrive in."""

    def test_declares_exactly_the_four_date_keys(self) -> None:
        """DATE_FIELDS is what the write paths normalise, so it is the model's date contract."""
        assert IsmsRiskAssessment.DATE_FIELDS == tuple(key.value for key in RISK_ASSESSMENT_DATE_KEYS)

    def test_the_declared_dates_are_the_schema_s_date_typed_fields(self) -> None:
        """
        A date field added to the schema without joining DATE_FIELDS would be stored as a wrapper.

        That is exactly the bug this model had: the schema typed the four dates as a plain 'dict', so
        the sub-document the frontend sends was persisted where a date belongs.

        Read from a freshly built schema rather than from IsmsRiskAssessment.SCHEMA on purpose:
        constructing a Cerberus Validator rewrites the 'anyof_type' shorthand into its expanded
        'anyof' form IN the dict it was handed, so the class attribute's shape depends on whether the
        REST app has been built in this process.
        """
        schema_date_keys = {
            key for key, rules in get_isms_risk_assessment_schema().items()
            if 'datetime' in rules.get('anyof_type', [])
        }

        assert schema_date_keys == set(IsmsRiskAssessment.DATE_FIELDS)

    def test_reads_the_wrapper_the_frontend_sends(self) -> None:
        """A payload carries a date as {'$date': <epoch millis>}."""
        assessment = IsmsRiskAssessment.from_data(_assessment_data())

        assert assessment.risk_assessment_date == STAMP

    def test_reads_a_stored_date_unchanged(self) -> None:
        """A document read back out of MongoDB already carries a real date."""
        assessment = IsmsRiskAssessment.from_data(
            _assessment_data(**{RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: STAMP})
        )

        assert assessment.risk_assessment_date is STAMP

    def test_reads_a_timestamp_string(self) -> None:
        """An API client may send a plain timestamp instead of the wrapper."""
        assessment = IsmsRiskAssessment.from_data(
            _assessment_data(**{RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: '2020-09-13T12:26:40Z'})
        )

        assert assessment.risk_assessment_date == STAMP

    @pytest.mark.parametrize('empty_value', [None, '', {}])
    def test_reads_an_emptied_optional_date_as_none(self, empty_value: Any) -> None:
        """An emptied date widget means 'no date' - the required-field guard refuses it separately."""
        assessment = IsmsRiskAssessment.from_data(
            _assessment_data(**{RiskAssessmentKey.AUDIT_DONE_DATE.value: empty_value})
        )

        assert assessment.audit_done_date is None

    def test_refuses_an_unreadable_date_instead_of_guessing_one(self) -> None:
        """
        The reason this model no longer parses with `fuzzy=True`.

        Fuzzy parsing turned a note like 'planned for Q3' into a date assembled from today's values -
        stored just as confidently as a correct one, and wrong in a way nothing about it looks wrong.
        """
        with pytest.raises(IsmsRiskAssessmentInitFromDataError) as err:
            IsmsRiskAssessment.from_data(
                _assessment_data(**{RiskAssessmentKey.AUDIT_DONE_DATE.value: 'planned for Q3'})
            )

        assert RiskAssessmentKey.AUDIT_DONE_DATE.value in str(err.value)

    def test_a_stored_date_reaches_the_wire_as_the_same_wrapper_it_arrived_in(self) -> None:
        """
        Which is why storing real dates changed nothing for the frontend.

        The response encoder serialises a datetime back into the wrapper, so the shape that went in
        is the shape that comes out - the change is in what MongoDB can do with the value.
        """
        assessment = IsmsRiskAssessment.from_data(_assessment_data())
        stored = IsmsRiskAssessment.to_json(assessment)

        assert default(stored[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value]) == {'$date': STAMP_MILLIS}

    def test_normalises_the_given_dict_in_place(self) -> None:
        """
        from_data normalises the caller's payload, not a copy.

        The update route hands its request body straight to from_data, so the normalised dates are
        what the rest of that handler sees.
        """
        data = _assessment_data()

        IsmsRiskAssessment.from_data(data)

        assert data[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value] == STAMP


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    closed key set                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestKeySet:
    """The model, the schema and the round-trip agree on one key set."""

    def test_to_json_emits_exactly_the_declared_keys(self) -> None:
        """
        The read routes answer with to_json(from_data(document)).

        A persisted key outside this set is therefore invisible in every response while still
        occupying the document, so the set has to be the whole document.
        """
        assessment = IsmsRiskAssessment.from_data(_assessment_data())

        assert set(IsmsRiskAssessment.to_json(assessment)) == {key.value for key in RiskAssessmentKey}

    def test_the_schema_validates_exactly_the_declared_keys_plus_the_transport_key(self) -> None:
        """
        The validator purges unknown keys, so the schema decides what a write route can even see.

        A schema key with no model field would be stored and then hidden; a model field with no schema
        key could never be written. The one legitimate extra is the assignments list, which every
        write route pops because it belongs to its own collection.
        """
        assert set(get_isms_risk_assessment_schema()) == (
            {key.value for key in RiskAssessmentKey} | {CONTROL_MEASURE_ASSIGNMENTS_KEY}
        )

    def test_round_trips_a_document_losslessly(self) -> None:
        """from_data and to_json are inverses over the closed key set."""
        data = _assessment_data(**{RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: STAMP})

        assert IsmsRiskAssessment.to_json(IsmsRiskAssessment.from_data(dict(data))) == data

    def test_ignores_a_key_it_does_not_declare(self) -> None:
        """A drifted document still loads; the undeclared key simply does not survive the round-trip."""
        assessment = IsmsRiskAssessment.from_data(_assessment_data(stowaway='value'))

        assert 'stowaway' not in IsmsRiskAssessment.to_json(assessment)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  pinned enum values                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPinnedEnumValues:
    """Validation, not the model, is where an unknown enum value is refused."""

    @pytest.mark.parametrize('key, enum_class', [
        (RiskAssessmentKey.OBJECT_ID_REF_TYPE, ObjectReferenceType),
        (RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE, PersonReferenceType),
        (RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE, PersonReferenceType),
        (RiskAssessmentKey.AUDITOR_ID_REF_TYPE, PersonReferenceType),
        (RiskAssessmentKey.RISK_TREATMENT_OPTION, TreatmentOption),
        (RiskAssessmentKey.PRIORITY, Priority),
    ])
    def test_every_enum_typed_field_is_pinned_to_its_enum(self, key: RiskAssessmentKey, enum_class: type) -> None:
        """
        The model stores the raw value, so an unpinned field would accept anything.

        'risk_treatment_option' and 'priority' were unpinned: an API client could store a treatment
        option the frontend has no name for and the reports cannot group by.
        """
        assert get_isms_risk_assessment_schema()[key.value]['allowed'] == [
            member.value for member in enum_class
        ]

    def test_the_model_keeps_the_raw_value(self) -> None:
        """The attributes are annotated as the primitives they hold, and this is why."""
        assessment = IsmsRiskAssessment.from_data(_assessment_data())

        assert assessment.priority == Priority.LOW.value
        assert not isinstance(assessment.priority, Priority)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       indexes                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIndexes:
    """The index declarations, which are contracts rather than implementation details."""

    @pytest.mark.parametrize('field', PERSON_CASCADE_FIELDS)
    def test_every_person_cascade_field_is_indexed(self, field: RiskAssessmentKey) -> None:
        """
        Deleting one CmdbPerson runs a filtered update per field over the whole collection.

        'risk_assessor_id' and the 'risk_owner_id' pair were the two that were missing, so half of
        that cascade was a collection scan while the other half was served from an index.
        """
        index_names = {index['name'] for index in IsmsRiskAssessment.INDEX_KEYS}

        assert field.value in index_names

    def test_every_index_names_the_field_it_keys_on(self) -> None:
        """Index reconciliation is name-based, so a name that lies about its key is unfixable in place."""
        for index in IsmsRiskAssessment.INDEX_KEYS:
            assert [key for key, _ in index['keys']] == [index['name']]

    def test_no_index_is_unique(self) -> None:
        """
        An object may be assessed against several risks, and a risk against several objects.

        Nothing about the pair is unique, which is why the collection has no compound identity index.
        """
        assert all(index['unique'] is False for index in IsmsRiskAssessment.INDEX_KEYS)

    def test_collection_name_is_pinned(self) -> None:
        """Seven managers name this collection for their cascades and in-use guards."""
        assert IsmsRiskAssessment.COLLECTION == 'isms.riskAssessment'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    error handling                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestErrorHandling:
    """Each of the three entry points reports its own failure type."""

    def test_init_is_keyword_only(self) -> None:
        """
        CmdbDAO reads its required init keys from the keyword arguments in __new__.

        A positional call is refused there, before __init__ runs - so it could never have constructed
        this class, and the keyword-only signature now says as much.
        """
        with pytest.raises(RequiredInitKeyNotFoundError):
            #pylint: disable=too-many-function-args
            IsmsRiskAssessment(RISK_ASSESSMENT_ID)

    def test_the_init_parameters_are_named_after_the_document_keys(self) -> None:
        """
        Which is what lets from_data pass the document through key by key.

        A parameter renamed away from its key would make from_data raise on every document.
        """
        with pytest.raises(IsmsRiskAssessmentInitError):
            # Every key present, so only the public_id cast can fail
            IsmsRiskAssessment(**{key.value: None for key in RiskAssessmentKey})

    def test_from_data_wraps_a_failing_init(self) -> None:
        """A document without a public_id cannot become an assessment."""
        data = _assessment_data()
        del data[RiskAssessmentKey.PUBLIC_ID.value]

        with pytest.raises(IsmsRiskAssessmentInitFromDataError):
            IsmsRiskAssessment.from_data(data)

    def test_to_json_wraps_a_failing_conversion(self) -> None:
        """Handed something that is not an assessment, it reports a conversion failure."""
        class _NotAnAssessment:
            """Carries none of the attributes to_json reads."""

        with pytest.raises(IsmsRiskAssessmentToJsonError):
            IsmsRiskAssessment.to_json(_NotAnAssessment())
