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
The ISMS references to persons and person groups, and their cleanup when one is deleted

Persons and person groups are CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes. An IsmsRiskAssessment and an
IsmsControlMeasureAssignment reference them by public_id:

**Reference keys** - ``PersonReferenceKeys`` lists, per ISMS collection, every key that references a person or a
group. ``RISK_ASSESSMENT_PERSON_REFERENCE_KEYS`` / ``CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS`` are what
``clear_object_person_references`` clears and what the ISMS write routes check, so the two always cover the same
keys. A polymorphic key is stored beside a ``_ref_type`` sibling naming whether it holds a person or a group.

**Cleanup** - ``clear_object_person_references`` runs from the object delete path for every deleted object. Object
public_ids are unique across all objects, so the id alone names what was deleted and no ``_ref_type`` filter is
needed. The module is manager-free: it takes the database manager and writes the ISMS collections directly
"""
from typing import Any, NamedTuple

from cmdb.database import MongoDatabaseManager

from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey

__all__: list[str] = [
    'CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS',
    'PERSON_ONLY_RISK_ASSESSMENT_KEYS',
    'POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS',
    'PersonReferenceKeys',
    'RISK_ASSESSMENT_PERSON_REFERENCE_KEYS',
    'ref_type_key',
    'clear_object_person_references',
]

# The IsmsRiskAssessment fields that hold either a person or a person group. Each is stored beside a
# '<key>_ref_type' sibling naming which of the two it is
POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_OWNER_ID.value,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
    RiskAssessmentKey.AUDITOR_ID.value,
)

# The IsmsControlMeasureAssignment field of the same shape
RESPONSIBLE_FOR_IMPLEMENTATION_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value

# The suffix that turns a polymorphic reference key into the key naming what it references
REF_TYPE_KEY_SUFFIX: str = '_ref_type'

# The IsmsRiskAssessment fields that can only ever hold a person - the assessor (a scalar) and the interviewed
# persons (a list)
PERSON_ONLY_RISK_ASSESSMENT_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_ASSESSOR_ID.value,
    RiskAssessmentKey.INTERVIEWED_PERSONS.value,
)


class PersonReferenceKeys(NamedTuple):
    """
    The keys of one ISMS collection that reference a person or a person group

    The one list of them: the delete cleanup clears exactly these keys and the write routes check exactly these
    keys, so a reference can never be one the write accepts and the cleanup does not clean
    """
    polymorphic: tuple[str, ...]
    person_only: tuple[str, ...]


RISK_ASSESSMENT_PERSON_REFERENCE_KEYS: PersonReferenceKeys = PersonReferenceKeys(
    polymorphic=POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    person_only=PERSON_ONLY_RISK_ASSESSMENT_KEYS,
)

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


def clear_object_person_references(
        dbm: MongoDatabaseManager,
        db_name: str,
        risk_assessment_collection: str,
        control_measure_assignment_collection: str,
        deleted_object_ids: list[int]) -> None:
    """
    Clears every ISMS reference to deleted CmdbObjects that were persons or person groups

    A scalar reference is nulled (its '_ref_type' sibling is left as it is, like an unset reference), a deleted
    person is pulled out of the interviewed persons. Callable for any deleted objects: an id no ISMS document
    references changes nothing. One write per key, however many ids

    Args:
        dbm (MongoDatabaseManager): Database manager performing the writes
        db_name (str): Name of the database owning the collections
        risk_assessment_collection (str): Collection of the IsmsRiskAssessments
        control_measure_assignment_collection (str): Collection of the IsmsControlMeasureAssignments
        deleted_object_ids (list[int]): public_ids of the deleted CmdbObjects; empty is a no-op
    """
    if not deleted_object_ids:
        return

    ids_filter: dict[str, Any] = {'$in': list(deleted_object_ids)}

    for key in (*POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS, RiskAssessmentKey.RISK_ASSESSOR_ID.value):
        dbm.update_many(risk_assessment_collection, db_name, {key: ids_filter}, {key: None})

    interviewed_key: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value

    dbm.update_many_raw(
        risk_assessment_collection,
        db_name,
        {interviewed_key: ids_filter},
        {'$pull': {interviewed_key: ids_filter}},
    )

    dbm.update_many(
        control_measure_assignment_collection,
        db_name,
        {RESPONSIBLE_FOR_IMPLEMENTATION_KEY: ids_filter},
        {RESPONSIBLE_FOR_IMPLEMENTATION_KEY: None},
    )
