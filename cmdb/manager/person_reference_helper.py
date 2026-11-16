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
The ISMS keys that reference a person or a person group - one list per ISMS collection

Persons and groups are objects of the Types carrying PERSON / PERSON_GROUP. A polymorphic key is stored beside a
``<key>_ref_type`` sibling naming which of the two it holds; a person-only key always means a person. The write check
of the ISMS routes (``isms_person_reference_helper``) and the clean-up after a person or group object is deleted
(``person_types.person_isms_cleanup``) read the same lists, so a key the write checks is a key the clean-up clears
"""
from typing import NamedTuple

from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS',
    'PERSON_ONLY_RISK_ASSESSMENT_KEYS',
    'POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS',
    'PersonReferenceKeys',
    'RISK_ASSESSMENT_PERSON_REFERENCE_KEYS',
    'ref_type_key',
]

# The IsmsRiskAssessment fields that hold either a person or a person group. Each is stored
# beside a '<key>_ref_type' sibling naming which of the two it is, and both halves are always filtered
# together - see ``person_isms_cleanup``
POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_OWNER_ID.value,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
    RiskAssessmentKey.AUDITOR_ID.value,
)

# The IsmsControlMeasureAssignment field of the same shape, with the same ref_type pairing
RESPONSIBLE_FOR_IMPLEMENTATION_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value

# The suffix that turns a polymorphic reference key into the key naming what it references
REF_TYPE_KEY_SUFFIX: str = '_ref_type'

# The IsmsRiskAssessment fields that can only ever hold a person - the assessor (a scalar) and the
# interviewed persons (a list). A plain {key: id} matches both shapes: a scalar equal to the id, a list holding it
PERSON_ONLY_RISK_ASSESSMENT_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_ASSESSOR_ID.value,
    RiskAssessmentKey.INTERVIEWED_PERSONS.value,
)


class PersonReferenceKeys(NamedTuple):
    """
    The keys of one ISMS collection that reference a person or a person group

    The one list of them: the delete clean-up clears exactly these keys and the write routes check exactly these
    keys, so a reference can never be one the write accepts and the clean-up does not clear
    """
    polymorphic: tuple[str, ...]
    person_only: tuple[str, ...]


# Every person reference of an IsmsRiskAssessment
RISK_ASSESSMENT_PERSON_REFERENCE_KEYS: PersonReferenceKeys = PersonReferenceKeys(
    polymorphic=POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    person_only=PERSON_ONLY_RISK_ASSESSMENT_KEYS,
)

# Every person reference of an IsmsControlMeasureAssignment
CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS: PersonReferenceKeys = PersonReferenceKeys(
    polymorphic=(RESPONSIBLE_FOR_IMPLEMENTATION_KEY,),
    person_only=(),
)


def ref_type_key(key: str) -> str:
    """
    The key of a polymorphic reference's '_ref_type' sibling

    Args:
        key (str): The reference field, e.g. ``risk_owner_id``

    Returns:
        str: The field naming what it references, e.g. ``risk_owner_id_ref_type``
    """
    return f'{key}{REF_TYPE_KEY_SUFFIX}'
