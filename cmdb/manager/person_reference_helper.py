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
Shared write paths of the CmdbPerson / CmdbPersonGroup pair

``PersonsManager`` and ``PersonGroupsManager`` are mirror images of one another: each owns one half of
a two-sided membership and each has to clean the same ISMS collections when its entity is deleted.
Written out twice, that was two copies of every ``$addToSet`` / ``$pull`` and two copies of the
polymorphic reference cascade, differing only in a collection name, an array key and a
``PersonReferenceType`` member - the shape where the two halves silently drift apart.

The module is deliberately manager-free: every function takes the database manager and writes one
collection, so either manager may call it without depending on the other (a manager must not, and this
is how the pair keeps that rule while sharing the code).

Two groups of functions:

**Membership** - ``add_member_to_documents`` / ``remove_member_from_documents`` maintain the reciprocal
array. Both sides store the relationship: a person lists their groups, a group lists its members, and
neither is derived from the other.

**ISMS references** - ``clear_polymorphic_risk_assessment_references`` and
``clear_control_measure_assignment_reference`` null the reference fields that may point at *either* a
person or a group. Every one of those fields is stored next to a ``_ref_type`` sibling saying which
kind it holds, so the filter must always name both: without the ref_type half, deleting person 7 would
also clear a field pointing at *group* 7
"""
from typing import Any, Iterable

from cmdb.database import MongoDatabaseManager

from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS',
    'add_member_to_documents',
    'remove_member_from_documents',
    'clear_polymorphic_risk_assessment_references',
    'clear_control_measure_assignment_reference',
]

# The IsmsRiskAssessment fields that hold either a CmdbPerson or a CmdbPersonGroup. Each is stored
# beside a '<key>_ref_type' sibling naming which of the two it is, and both halves are always filtered
# together - see clear_polymorphic_person_references
POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_OWNER_ID.value,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
    RiskAssessmentKey.AUDITOR_ID.value,
)

# The IsmsControlMeasureAssignment field of the same shape, with the same ref_type pairing
RESPONSIBLE_FOR_IMPLEMENTATION_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value
RESPONSIBLE_FOR_IMPLEMENTATION_REF_TYPE_KEY: str = (
    ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value
)

# The suffix that turns a polymorphic reference key into the key naming what it references
REF_TYPE_KEY_SUFFIX: str = '_ref_type'

# The key every document of both collections is addressed by
PUBLIC_ID_KEY: str = RiskAssessmentKey.PUBLIC_ID.value


def add_member_to_documents(
        dbm: MongoDatabaseManager,
        db_name: str,
        collection: str,
        array_key: str,
        member_id: int,
        document_ids: Iterable[int] | None) -> None:
    """
    Adds one public_id to an array key of the named documents, in a single bulk update

    Uses '$addToSet', so a member already listed is not duplicated and the caller needs no per-document
    read to find out

    Args:
        dbm (MongoDatabaseManager): Database manager performing the write
        db_name (str): Name of the database owning the collection
        collection (str): Collection holding the documents to update
        array_key (str): The array key the member is added to
        member_id (int): public_id to add
        document_ids (Iterable[int] | None): public_ids of the documents to update; nothing is written
                                             for an empty or missing selection
    """
    if not document_ids:
        return

    dbm.update_many(
        collection,
        db_name,
        {PUBLIC_ID_KEY: {'$in': list(document_ids)}},
        {array_key: member_id},
        add_to_set=True,
    )


def remove_member_from_documents(
        dbm: MongoDatabaseManager,
        db_name: str,
        collection: str,
        array_key: str,
        member_id: int,
        document_ids: Iterable[int] | None = None) -> None:
    """
    Removes one public_id from an array key, in a single bulk '$pull'

    With document_ids the pull is restricted to those documents (the update case: only the memberships
    the caller actually dropped); without it, it reaches every document that still lists the member,
    which is what a deletion needs

    Args:
        dbm (MongoDatabaseManager): Database manager performing the write
        db_name (str): Name of the database owning the collection
        collection (str): Collection holding the documents to update
        array_key (str): The array key the member is removed from
        member_id (int): public_id to remove
        document_ids (Iterable[int] | None): public_ids to restrict the pull to. Defaults to None,
                                             meaning every document listing the member
    """
    criteria: dict[str, Any] = {array_key: member_id}

    if document_ids is not None:
        criteria[PUBLIC_ID_KEY] = {'$in': list(document_ids)}

    dbm.update_many_pull(
        collection,
        db_name,
        criteria,
        {array_key: member_id},
    )


def clear_polymorphic_risk_assessment_references(
        dbm: MongoDatabaseManager,
        db_name: str,
        collection: str,
        referenced_id: int,
        reference_type: PersonReferenceType) -> None:
    """
    Nulls the polymorphic IsmsRiskAssessment references pointing at one deleted person or group

    The three fields that may hold either kind. Each is filtered together with its '_ref_type' sibling,
    so a CmdbPerson and a CmdbPersonGroup that happen to share a public_id are never confused for one
    another. The assessor and the interviewed persons are NOT here: both can only ever be persons, so
    they are the person manager's own business

    Args:
        dbm (MongoDatabaseManager): Database manager performing the writes
        db_name (str): Name of the database owning the collection
        collection (str): Collection of the IsmsRiskAssessments
        referenced_id (int): public_id of the deleted CmdbPerson or CmdbPersonGroup
        reference_type (PersonReferenceType): Which of the two kinds was deleted
    """
    for key in POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS:
        dbm.update_many(
            collection,
            db_name,
            {key: referenced_id, f'{key}{REF_TYPE_KEY_SUFFIX}': reference_type.value},
            {key: None},
        )


def clear_control_measure_assignment_reference(
        dbm: MongoDatabaseManager,
        db_name: str,
        collection: str,
        referenced_id: int,
        reference_type: PersonReferenceType) -> None:
    """
    Nulls the IsmsControlMeasureAssignment reference pointing at one deleted person or group

    The assignment carries a single polymorphic reference - who is responsible for implementing the
    measure - filtered by its '_ref_type' sibling for the same reason as the assessment fields above

    Args:
        dbm (MongoDatabaseManager): Database manager performing the write
        db_name (str): Name of the database owning the collection
        collection (str): Collection of the IsmsControlMeasureAssignments
        referenced_id (int): public_id of the deleted CmdbPerson or CmdbPersonGroup
        reference_type (PersonReferenceType): Which of the two kinds was deleted
    """
    dbm.update_many(
        collection,
        db_name,
        {
            RESPONSIBLE_FOR_IMPLEMENTATION_KEY: referenced_id,
            RESPONSIBLE_FOR_IMPLEMENTATION_REF_TYPE_KEY: reference_type.value,
        },
        {RESPONSIBLE_FOR_IMPLEMENTATION_KEY: None},
    )
