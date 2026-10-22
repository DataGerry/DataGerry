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
The steps of ``GET /isms/risk_assessments/`` around its one query

* ``expand_object_scope_filter``: a filter scoped to one OBJECT also matches the assessments of every
  CmdbObjectGroup that object belongs to. Every other clause of the filter is kept, so the list's search narrows
  the expanded scope like any other
* ``collect_naming_ids`` / ``fetch_naming_lookups``: the ids a page of assessments references, then one projected
  read per collection for their display names
* ``build_ra_naming`` / ``named_risk_assessment``: one assessment with its ``naming`` block, from those lookups alone
"""
from dataclasses import dataclass, field
from typing import Any

from cmdb.database.database_constants import MONGO_AND_OPERATOR, MONGO_ID_FIELD, PUBLIC_ID_FIELD
from cmdb.manager import ObjectGroupsManager, ObjectsManager, PersonGroupsManager, PersonsManager, RiskManager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.object_group_model.object_group_constants import ObjectGroupKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.person_group_model.person_group_constants import PersonGroupKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.person_model.person_constants import PersonKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder

from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    RISK_ASSESSMENT_NAMING_KEY,
    RiskAssessmentNamingKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

# The keys a clause of an object scope may carry: the scope is the pair, each in a clause of its own
OBJECT_SCOPE_KEYS: frozenset[str] = frozenset({
    RiskAssessmentKey.OBJECT_ID.value,
    RiskAssessmentKey.OBJECT_ID_REF_TYPE.value,
})


@dataclass(frozen=True)
class RiskAssessmentNamingIds:
    """
    The ids a page of RiskAssessments references, one set per collection that names them

    Interviewed and responsible persons are kept apart because the assessment holds them under different keys; both
    are read from the persons collection in one query
    """
    risk_ids: set[int] = field(default_factory=set)
    object_group_ids: set[int] = field(default_factory=set)
    object_ids: set[int] = field(default_factory=set)
    person_ids: set[int] = field(default_factory=set)
    responsible_person_ids: set[int] = field(default_factory=set)
    responsible_person_group_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class RiskAssessmentNamingLookups:
    """
    The display names of what a page of RiskAssessments references, keyed by public_id

    ``persons`` serves both the interviewed and the responsible persons. ``object_summaries`` only holds the objects
    the caller may READ, so an unreadable object stays unnamed
    """
    risks: dict[int, str] = field(default_factory=dict)
    object_groups: dict[int, str] = field(default_factory=dict)
    object_summaries: dict[int, str] = field(default_factory=dict)
    persons: dict[int, str] = field(default_factory=dict)
    person_groups: dict[int, str] = field(default_factory=dict)


def is_object_scope_clause(clause: Any) -> bool:
    """
    Whether a clause of a filter's ``$and`` is one half of an object scope

    Args:
        clause (Any): One entry of the filter's ``$and`` list

    Returns:
        bool: True for a non-empty dict carrying only ``object_id`` and / or ``object_id_ref_type``
    """
    return isinstance(clause, dict) and bool(clause) and set(clause) <= OBJECT_SCOPE_KEYS


def scoped_object_id(scope_clauses: list[dict[str, Any]]) -> int | None:
    """
    The public_id of the CmdbObject a filter's scope clauses name

    Args:
        scope_clauses (list[dict[str, Any]]): The clauses ``is_object_scope_clause`` accepted

    Returns:
        int | None: The id, or None when the scope names no OBJECT, or names its id as anything but an integer (an
            operator expression, say)
    """
    scope: dict[str, Any] = {}

    for clause in scope_clauses:
        scope.update(clause)

    object_id: Any = scope.get(RiskAssessmentKey.OBJECT_ID.value)

    if scope.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) != ObjectReferenceType.OBJECT:
        return None

    if not isinstance(object_id, int) or isinstance(object_id, bool):
        return None

    return object_id


def object_or_group_scope(object_id: int, group_ids: list[int]) -> dict[str, Any]:
    """
    The scope matching the assessments of an object and of the CmdbObjectGroups it belongs to

    Args:
        object_id (int): public_id of the CmdbObject
        group_ids (list[int]): public_ids of the CmdbObjectGroups containing it

    Returns:
        dict[str, Any]: An ``$or`` of the object's own scope and the groups' scope
    """
    return Builder.or_([
        Builder.and_([
            {RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: ObjectReferenceType.OBJECT},
            {RiskAssessmentKey.OBJECT_ID.value: object_id},
        ]),
        Builder.and_([
            {RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: ObjectReferenceType.OBJECT_GROUP},
            Builder.in_(RiskAssessmentKey.OBJECT_ID.value, group_ids),
        ]),
    ])


def expand_object_scope_filter(query_filter: Any, request_user: CmdbUser) -> Any:
    """
    Widens a filter scoped to one CmdbObject to the assessments of the groups that object belongs to

    The scope is an ``$and`` holding ``{object_id_ref_type: OBJECT}`` and ``{object_id: <int>}``, each in a clause of
    its own - the shape the frontend's list sends. Both clauses are replaced by ``object_or_group_scope``; every other
    clause of the ``$and``, and every other top-level key, is kept beside it. A filter of any other shape, a scope
    naming no integer id and an object that does not exist leave the filter as it is

    Args:
        query_filter (Any): The list's ``filter`` parameter
        request_user (CmdbUser): CmdbUser requesting the list

    Raises:
        ObjectsManagerGetError: When the object could not be read
        BaseManagerGetError: When its groups could not be read

    Returns:
        Any: The filter to query with
    """
    if not isinstance(query_filter, dict) or not isinstance(query_filter.get(MONGO_AND_OPERATOR), list):
        return query_filter

    clauses: list[Any] = query_filter[MONGO_AND_OPERATOR]
    object_id: int | None = scoped_object_id([clause for clause in clauses if is_object_scope_clause(clause)])

    if object_id is None:
        return query_filter

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    target_object: dict[str, Any] | None = objects_manager.get_object(object_id)

    if target_object is None:
        return query_filter

    # Every group the object belongs to: the STATIC ones listing the object itself and the DYNAMIC ones listing its
    # type. The manager owns that pairing and answers both in one query
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)
    group_ids: list[int] = object_groups_manager.find_group_ids_containing(
        object_id, target_object[CmdbObjectKey.TYPE_ID.value],
    )

    other_keys: dict[str, Any] = {key: value for key, value in query_filter.items() if key != MONGO_AND_OPERATOR}
    other_clauses: list[Any] = [clause for clause in clauses if not is_object_scope_clause(clause)]

    return {**other_keys, **Builder.and_([object_or_group_scope(object_id, group_ids), *other_clauses])}


def collect_naming_ids(risk_assessments: list[IsmsRiskAssessment]) -> RiskAssessmentNamingIds:
    """
    The ids a page of RiskAssessments references, sorted by the collection that names them

    Args:
        risk_assessments (list[IsmsRiskAssessment]): The page

    Returns:
        RiskAssessmentNamingIds: One id set per collection
    """
    ids: RiskAssessmentNamingIds = RiskAssessmentNamingIds()

    for risk_assessment in risk_assessments:
        if risk_assessment.risk_id:
            ids.risk_ids.add(risk_assessment.risk_id)

        if risk_assessment.object_id_ref_type == ObjectReferenceType.OBJECT_GROUP:
            ids.object_group_ids.add(risk_assessment.object_id)
        elif risk_assessment.object_id_ref_type == ObjectReferenceType.OBJECT:
            ids.object_ids.add(risk_assessment.object_id)

        if isinstance(risk_assessment.interviewed_persons, list):
            ids.person_ids.update(risk_assessment.interviewed_persons)

        if not risk_assessment.responsible_persons_id:
            continue

        if risk_assessment.responsible_persons_id_ref_type == PersonReferenceType.PERSON:
            ids.responsible_person_ids.add(risk_assessment.responsible_persons_id)
        elif risk_assessment.responsible_persons_id_ref_type == PersonReferenceType.PERSON_GROUP:
            ids.responsible_person_group_ids.add(risk_assessment.responsible_persons_id)

    return ids


def name_lookup(manager: BaseManager, public_ids: set[int], name_key: str) -> dict[int, str]:
    """
    The display names of the documents of one collection, read in one projected query

    Args:
        manager (BaseManager): The manager of the collection
        public_ids (set[int]): The documents to name; an empty set reads nothing
        name_key (str): The key holding a document's display name

    Raises:
        BaseManagerGetError: When the read failed

    Returns:
        dict[int, str]: public_id -> display name, for the documents that exist
    """
    if not public_ids:
        return {}

    documents: list[dict[str, Any]] = manager.find_all(
        criteria=Builder.in_(PUBLIC_ID_FIELD, sorted(public_ids)),
        projection={MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1, name_key: 1},
    )

    return {document[PUBLIC_ID_FIELD]: document.get(name_key) for document in documents}


def fetch_naming_lookups(ids: RiskAssessmentNamingIds, request_user: CmdbUser) -> RiskAssessmentNamingLookups:
    """
    Reads the display names of everything a page of RiskAssessments references

    One projected query per collection, and none for a collection the page references nothing of. The objects are
    read as the caller: an object of a Type their group may not READ gets no summary line

    Args:
        ids (RiskAssessmentNamingIds): What the page references
        request_user (CmdbUser): CmdbUser requesting the list

    Raises:
        BaseManagerGetError: When a name read failed
        ObjectsManagerGetError: When the summary lines could not be read

    Returns:
        RiskAssessmentNamingLookups: The names, keyed by public_id
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)
    persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
    person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP, request_user)

    object_summaries: dict[int, str] = {}

    if ids.object_ids:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        object_summaries = objects_manager.get_summary_lines_lookup(
            sorted(ids.object_ids), user=request_user, permission=AccessControlPermission.READ,
        )

    return RiskAssessmentNamingLookups(
        risks=name_lookup(risk_manager, ids.risk_ids, RiskKey.NAME.value),
        object_groups=name_lookup(object_groups_manager, ids.object_group_ids, ObjectGroupKey.NAME.value),
        object_summaries=object_summaries,
        persons=name_lookup(
            persons_manager, ids.person_ids | ids.responsible_person_ids, PersonKey.DISPLAY_NAME.value,
        ),
        person_groups=name_lookup(
            person_groups_manager, ids.responsible_person_group_ids, PersonGroupKey.NAME.value,
        ),
    )


def build_ra_naming(
        risk_assessment: IsmsRiskAssessment,
        lookups: RiskAssessmentNamingLookups) -> dict[str, Any]:
    """
    Builds the display-naming block for one IsmsRiskAssessment from pre-fetched lookups

    Resolves the risk name, the referenced object (summary line) or object group (name), the interviewed persons'
    names and the responsible person / person group name. All values come from the lookups, so this stays a pure,
    database-free helper

    Args:
        risk_assessment (IsmsRiskAssessment): The assessment to name
        lookups (RiskAssessmentNamingLookups): The names of everything the page references

    Returns:
        dict[str, Any]: The naming block for the assessment's ``naming`` field
    """
    naming: dict[str, Any] = {
        RiskAssessmentNamingKey.RISK_ID_NAME.value: lookups.risks.get(risk_assessment.risk_id),
        RiskAssessmentNamingKey.OBJECT_GROUP_ID_NAME.value: None,
        RiskAssessmentNamingKey.OBJECT_ID_NAME.value: None,
        RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value: None,
        RiskAssessmentNamingKey.RESPONSIBLE_PERSONS_ID_NAME.value: None,
    }

    if risk_assessment.object_id_ref_type == ObjectReferenceType.OBJECT_GROUP:
        naming[RiskAssessmentNamingKey.OBJECT_GROUP_ID_NAME.value] = lookups.object_groups.get(
            risk_assessment.object_id
        )

    if risk_assessment.object_id_ref_type == ObjectReferenceType.OBJECT:
        naming[RiskAssessmentNamingKey.OBJECT_ID_NAME.value] = lookups.object_summaries.get(risk_assessment.object_id)

    if risk_assessment.interviewed_persons:
        naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value] = [
            lookups.persons[person_id] for person_id in risk_assessment.interviewed_persons
            if person_id in lookups.persons
        ] or None

    naming[RiskAssessmentNamingKey.RESPONSIBLE_PERSONS_ID_NAME.value] = responsible_name(risk_assessment, lookups)

    return naming


def responsible_name(risk_assessment: IsmsRiskAssessment, lookups: RiskAssessmentNamingLookups) -> str | None:
    """
    The display name of an assessment's responsible person or person group

    Args:
        risk_assessment (IsmsRiskAssessment): The assessment
        lookups (RiskAssessmentNamingLookups): The names of everything the page references

    Returns:
        str | None: The name from the lookup its ref_type names, None when it names nothing resolvable
    """
    if not risk_assessment.responsible_persons_id:
        return None

    if risk_assessment.responsible_persons_id_ref_type == PersonReferenceType.PERSON:
        return lookups.persons.get(risk_assessment.responsible_persons_id)

    if risk_assessment.responsible_persons_id_ref_type == PersonReferenceType.PERSON_GROUP:
        return lookups.person_groups.get(risk_assessment.responsible_persons_id)

    return None


def named_risk_assessment(
        risk_assessment: IsmsRiskAssessment,
        lookups: RiskAssessmentNamingLookups) -> dict[str, Any]:
    """
    One listed RiskAssessment: its document with the ``naming`` block

    Args:
        risk_assessment (IsmsRiskAssessment): The assessment
        lookups (RiskAssessmentNamingLookups): The names of everything the page references

    Returns:
        dict[str, Any]: The assessment's JSON document carrying ``naming``
    """
    document: dict[str, Any] = IsmsRiskAssessment.to_json(risk_assessment)
    document[RISK_ASSESSMENT_NAMING_KEY] = build_ra_naming(risk_assessment, lookups)

    return document
