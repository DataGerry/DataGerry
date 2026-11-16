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
Deleting a person or group object: what it means for the ISMS documents naming it

A risk assessment and a control-measure assignment name persons and groups by object id, a polymorphic key beside its
``<key>_ref_type`` (PERSON / PERSON_GROUP). The object delete path asks two things of the targets that are persons or
groups (``marked_targets``, by the marker the object carries):

  - ``count_owned_risk_assessments`` - the risk owner is a required field, so a cascade never empties it: the delete is
    refused while a target owns an assessment
  - ``clear_isms_person_references`` - every other reference is cleared after the delete, best-effort: the polymorphic
    keys nulled where id and ref_type match, the assessor nulled, the interviewed persons pulled - one update per key
    for the whole selection

The keys are ``person_reference_helper``'s, the same lists the ISMS write check judges
"""
from typing import Any, Iterable

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    ref_type_key,
)
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'clear_isms_person_references',
    'count_owned_risk_assessments',
    'marked_targets',
]

# The reference keys of each ISMS collection
_REFERENCE_KEYS: dict[str, Any] = {
    IsmsRiskAssessment.COLLECTION: RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    IsmsControlMeasureAssignment.COLLECTION: CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
}


def marked_targets(target_objects: Iterable[dict[str, Any]]) -> dict[PersonReferenceType, list[int]]:
    """
    The targets that are persons or groups, by the reference type naming them

    Read off the marker the object document carries - its Type's

    Args:
        target_objects (Iterable[dict[str, Any]]): The object documents

    Returns:
        dict[PersonReferenceType, list[int]]: The public_ids per kind; a kind without one is left out
    """
    targets: dict[PersonReferenceType, list[int]] = {}

    for document in target_objects:
        marker: Any = document.get(CmdbObjectKey.SPECIAL_TYPE.value)

        if PersonReferenceType.is_valid(marker):
            targets.setdefault(PersonReferenceType(marker), []).append(document[CmdbObjectKey.PUBLIC_ID.value])

    return targets


def _polymorphic_criteria(key: str, reference_type: PersonReferenceType, ids: list[int]) -> dict[str, Any]:
    """
    A polymorphic key naming one of the ids as the kind - the id AND its ref_type, never the id alone

    Args:
        key (str): The reference key
        reference_type (PersonReferenceType): The kind
        ids (list[int]): The ids

    Returns:
        dict[str, Any]: The filter
    """
    return {key: {'$in': ids}, ref_type_key(key): reference_type.value}


def count_owned_risk_assessments(manager: BaseManager, targets: dict[PersonReferenceType, list[int]]) -> int:
    """
    How many risk assessments a target owns - one existence-capped count per kind

    Args:
        manager (BaseManager): Any manager of the tenant's database
        targets (dict[PersonReferenceType, list[int]]): The person / group targets (``marked_targets``)

    Raises:
        BaseManagerGetError: When a count fails

    Returns:
        int: The owned assessments; 0 when none
    """
    return sum(
        manager.count_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            _polymorphic_criteria(RiskAssessmentKey.RISK_OWNER_ID.value, reference_type, ids),
        )
        for reference_type, ids in targets.items() if ids
    )


def clear_isms_person_references(manager: BaseManager, targets: dict[PersonReferenceType, list[int]]) -> None:
    """
    Clears every ISMS reference to the deleted persons and groups

    The polymorphic keys are nulled where id and ref_type match - the risk owner among them only in name: the delete
    was refused while one was owned. The person-only keys apply to persons alone: a scalar is nulled, a list pulls them

    Args:
        manager (BaseManager): Any manager of the tenant's database
        targets (dict[PersonReferenceType, list[int]]): The deleted persons / groups (``marked_targets``)

    Raises:
        BaseManagerUpdateError: When an update fails - the steps before it are written
    """
    for collection, keys in _REFERENCE_KEYS.items():
        for reference_type, ids in targets.items():
            for key in keys.polymorphic:
                manager.update_many(_polymorphic_criteria(key, reference_type, ids), {key: None}, collection=collection)

        person_ids: list[int] = targets.get(PersonReferenceType.PERSON) or []

        if not person_ids:
            continue

        for key in keys.person_only:
            if key == RiskAssessmentKey.INTERVIEWED_PERSONS.value:
                manager.update_many_raw({key: {'$in': person_ids}}, {'$pull': {key: {'$in': person_ids}}},
                                        collection=collection)
            else:
                manager.update_many({key: {'$in': person_ids}}, {key: None}, collection=collection)
