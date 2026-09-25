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
Implementation of IsmsRiskAssessment in DataGerry - ISMS

An IsmsRiskAssessment evaluates one IsmsRisk for one CmdbObject or CmdbObjectGroup, before and after
treatment (collection ``isms.riskAssessment``). Three properties of this document are invariants the
rest of the ISMS relies on:

**Its four date fields are real BSON dates.** They arrive as the Mongo extended-JSON wrapper
``{'$date': <epoch millis>}`` - the shape every DataGerry response uses for a datetime and therefore
the shape the frontend sends back - and are normalised into ``datetime`` objects on the way in, by
``normalize_document`` here and by ``GenericManager`` on the raw-dict write paths. Storing the wrapper itself
would leave a sub-document where a date belongs, which MongoDB cannot sort, range-filter or
``$dateToString`` - the reports could only ever project such a value, never query it. The wire format
is the wrapper either way, because ``cmdb.database.json_codec.default`` serialises a datetime back into
the same wrapper.

**Its key set is closed.** ``RiskAssessmentKey`` names every persisted key, and the shared
``CmdbDAO.from_data`` / ``to_json`` it declares as ``KEYS`` are a lossless round-trip over exactly that
set - which the read routes depend on, since they answer with ``to_json(from_data(document))``.
``REQUIRED_INIT_KEYS`` refuses a document that names no risk or no assessed object, and nothing more:
a list route reads every row through the model, so a stricter read would let one incomplete row fail
the whole page. A key stored outside the set would be invisible in every response while still
occupying the document, so no write path may persist one: ``control_measure_assignments`` travels in
the same payload but belongs to its own collection and is popped by each write route before the
assessment is stored.

**Its enum-typed fields hold the enum's raw value, not a member.** The values are pinned by the
Cerberus schema (``allowed`` lists built from the enums), so validation - not the model - is what
refuses an unknown reference type, treatment option or priority. The attributes are annotated as the
primitives they actually hold; the docstrings name the enum that defines the allowed values
"""
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.class_schema.isms_model.isms_risk_assessment_schema import get_isms_risk_assessment_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_assessment_constants import (
    RISK_ASSESSMENT_DATE_KEYS,
    RISK_ASSESSMENT_REQUIRED_DOCUMENT_KEYS,
    RiskAssessmentKey,
)

from cmdb.errors.models.isms_risk_assessment import (
    IsmsRiskAssessmentInitError,
    IsmsRiskAssessmentInitFromDataError,
    IsmsRiskAssessmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsRiskAssessment - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
#pylint: disable=R0902
class IsmsRiskAssessment(CmdbDAO):
    """
    Implementation of IsmsRiskAssessment

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskAssessment"

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(RiskAssessmentKey.RISK_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.OBJECT_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.OBJECT_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.OBJECT_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.INTERVIEWED_PERSONS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.INTERVIEWED_PERSONS.value,
            'unique': False
        },
        # Both person-reference halves of the assessor / owner pair are indexed like the responsible
        # and auditor pairs below: deleting one CmdbPerson runs a filtered update over every one of
        # them (see PersonsManager.remove_person_from_risk_assessments), and a missing index turns that
        # cascade into a collection scan
        {
            'keys': [(RiskAssessmentKey.RISK_ASSESSOR_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RISK_OWNER_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_OWNER_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.IMPLEMENTATION_STATUS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.AUDITOR_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.AUDITOR_ID.value,
            'unique': False
        },
    ]

    SCHEMA: dict = get_isms_risk_assessment_schema()

    # The date-typed fields every write path normalises into real BSON dates
    DATE_FIELDS: tuple[str, ...] = tuple(date_key.value for date_key in RISK_ASSESSMENT_DATE_KEYS)

    # The shared from_data / to_json; REQUIRED_INIT_KEYS refuses a document without its identity
    KEYS = RiskAssessmentKey
    REQUIRED_INIT_KEYS: list[str] = RISK_ASSESSMENT_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsRiskAssessmentInitFromDataError
    TO_JSON_ERROR = IsmsRiskAssessmentToJsonError


    #pylint: disable=R0913, R0914
    def __init__(
            self,
            *,
            public_id: int,
            risk_id: int,
            object_id_ref_type: str,
            object_id: int,
            risk_calculation_before: dict[str, Any],
            risk_assessor_id: int | None,
            risk_owner_id_ref_type: str,
            risk_owner_id: int | None,
            interviewed_persons: list[int] | None,
            risk_assessment_date: datetime | None,
            additional_info: str | None,
            risk_treatment_option: str | None,
            responsible_persons_id_ref_type: str,
            responsible_persons_id: int | None,
            risk_treatment_description: str | None,
            planned_implementation_date: datetime | None,
            implementation_status: int | None,
            finished_implementation_date: datetime | None,
            required_resources: str | None,
            costs_for_implementation: float | None,
            costs_for_implementation_currency: str | None,
            priority: int | None,
            risk_calculation_after: dict[str, Any],
            audit_done_date: datetime | None,
            auditor_id_ref_type: str,
            auditor_id: int | None,
            audit_result: str | None
        ) -> None:
        """
        Initialises an IsmsRiskAssessment

        Keyword-only by design: CmdbDAO validates its required init keys in ``__new__``, reading them
        from the keyword arguments, so a positional call could never have constructed this class

        Args:
            public_id (int): public_id of the IsmsRiskAssessment
            risk_id (int): public_id of referenced IsmsRisk
            object_id_ref_type (str): Which collection 'object_id' points at, an ObjectReferenceType value
            object_id (int): public_id of referenced CmdbObject or CmdbObjectGroup
            risk_calculation_before (dict): sliders before treatment
            risk_assessor_id (int | None): public_id of CmdbPerson
            risk_owner_id_ref_type (str): Which collection 'risk_owner_id' points at, a
                PersonReferenceType value
            risk_owner_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            interviewed_persons (list | None): Multiselect of CmdbPersons
            risk_assessment_date (datetime | None): Date of risk calculation before treatment
            additional_info (str | None): Additional information field value
            risk_treatment_option (str | None): A TreatmentOption value
            responsible_persons_id_ref_type (str): Which collection 'responsible_persons_id' points at,
                a PersonReferenceType value
            responsible_persons_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            risk_treatment_description (str | None): Additional information text area field
            planned_implementation_date (datetime | None): Date of planned implementation
            implementation_status (int | None): public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            finished_implementation_date (datetime | None): Date of finished implementation
            required_resources (str | None): Required resources text area field
            costs_for_implementation (float | None): Costs for implementation
            costs_for_implementation_currency (str | None): Costs for implementation currency
            priority (int | None): A Priority value (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            risk_calculation_after (dict): sliders after treatment
            audit_done_date (datetime | None): Audit done date
            auditor_id_ref_type (str): Which collection 'auditor_id' points at, a PersonReferenceType value
            auditor_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            audit_result (str | None): Audit result text area field

        Raises:
            IsmsRiskAssessmentInitError: When the IsmsRiskAssessment could not be initialised
        """
        try:
            self.risk_id = risk_id
            self.object_id_ref_type = object_id_ref_type
            self.object_id = object_id
            self.risk_calculation_before = risk_calculation_before
            self.risk_assessor_id = risk_assessor_id
            self.risk_owner_id_ref_type = risk_owner_id_ref_type
            self.risk_owner_id = risk_owner_id
            self.interviewed_persons = interviewed_persons
            self.risk_assessment_date = risk_assessment_date
            self.additional_info = additional_info
            self.risk_treatment_option = risk_treatment_option
            self.responsible_persons_id_ref_type = responsible_persons_id_ref_type
            self.responsible_persons_id = responsible_persons_id
            self.risk_treatment_description = risk_treatment_description
            self.planned_implementation_date = planned_implementation_date
            self.implementation_status = implementation_status
            self.finished_implementation_date = finished_implementation_date
            self.required_resources = required_resources
            self.costs_for_implementation = costs_for_implementation
            self.costs_for_implementation_currency = costs_for_implementation_currency
            self.priority = priority
            self.risk_calculation_after = risk_calculation_after
            self.audit_done_date = audit_done_date
            self.auditor_id_ref_type = auditor_id_ref_type
            self.auditor_id = auditor_id
            self.audit_result = audit_result

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskAssessmentInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises the four date fields of a raw document IN PLACE before the shared from_data reads it

        Reads a document coming out of MongoDB as well as a validated request payload: a payload carries
        the dates as ``{'$date': ...}`` wrappers or timestamp strings, a stored document as real dates. A
        date that cannot be read is refused instead of guessed - a fuzzy parse would turn
        'implementation planned for Q3' into a date built from today

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place

        Raises:
            ValueError: If a present date field is not a readable timestamp; the shared from_data
                reports it as IsmsRiskAssessmentInitFromDataError
        """
        unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")
