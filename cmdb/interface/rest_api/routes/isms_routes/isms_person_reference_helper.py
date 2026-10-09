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
The write-side check of the ISMS person references

An IsmsRiskAssessment and an IsmsControlMeasureAssignment reference CmdbPersons and CmdbPersonGroups by public_id.
A polymorphic reference is stored beside a ``<key>_ref_type`` sibling naming which of the two collections the id
is in; a person-only reference always means a CmdbPerson. The delete cascades clear a reference by filtering on
BOTH halves, so a reference is only ever cleaned when the id exists in the collection its ref_type names. The
write routes therefore resolve every reference against that collection before anything is written:

* ``collect_person_references`` reads every reference a document carries, as ``PersonReference`` triples
* ``new_person_references`` keeps the ones an update introduces - a reference the stored document already holds
  is not judged again, so a document carrying a reference that went stale can still be saved
* ``abort_on_unknown_person_references`` answers 400 for a reference that is not a public_id, names no known
  reference type, or names an id its collection does not hold - one projected ``$in`` query per collection
* ``check_person_references`` is that check bound to the request user's tenant, for the routes

The keys come from ``person_reference_helper``, the same lists the delete cascades clear.
"""
from http import HTTPStatus
from typing import Any, NamedTuple

from flask import abort

from cmdb.manager import PersonGroupsManager, PersonsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.person_reference_helper import PersonReferenceKeys, ref_type_key

from cmdb.errors.manager.persons_manager import PersonsManagerGetError
from cmdb.errors.manager.person_groups_manager import PersonGroupsManagerGetError
from cmdb.models.user_model import CmdbUser
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.routes_helper import abort_on_unknown_references
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import PERSON_GROUP_LABEL, PERSON_LABEL
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    INVALID_PERSON_REFERENCE_ID_MSG,
    REFERENCE_LOOKUP_FAILED_MSG,
    UNKNOWN_PERSON_REFERENCE_TYPE_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PERSON_REFERENCE_LOOKUP_ERRORS',
    'PersonReference',
    'abort_on_unknown_person_references',
    'check_person_references',
    'collect_person_references',
    'new_person_references',
]

# The ref_type values a polymorphic reference may carry, in the order the refusal lists them
_ALLOWED_REFERENCE_TYPES: list[str] = [reference_type.value for reference_type in PersonReferenceType]

# The handle_manager_errors entries of a route that runs the check: a failed lookup is a 400, like every other
# manager read failure of the ISMS routes
PERSON_REFERENCE_LOOKUP_ERRORS: dict[type[Exception], str] = {
    PersonsManagerGetError: REFERENCE_LOOKUP_FAILED_MSG.format(label=PERSON_LABEL),
    PersonGroupsManagerGetError: REFERENCE_LOOKUP_FAILED_MSG.format(label=PERSON_GROUP_LABEL),
}


class PersonReference(NamedTuple):
    """
    One person reference of a document, as sent

    Attributes:
        key (str): The document key holding it
        public_id (Any): The referenced public_id, unvalidated
        reference_type (Any): The collection it names - the ``_ref_type`` sibling's value for a polymorphic
            reference, ``PersonReferenceType.PERSON``'s value for a person-only one
    """
    key: str
    public_id: Any
    reference_type: Any


def _referenced_ids(value: Any) -> list[Any]:
    """
    The ids a person-only key holds: none, one scalar, or every entry of a list

    Args:
        value (Any): The key's value

    Returns:
        list[Any]: The referenced ids, unvalidated
    """
    if value is None:
        return []

    return list(value) if isinstance(value, list) else [value]


def collect_person_references(document: dict[str, Any], keys: PersonReferenceKeys) -> list[PersonReference]:
    """
    Every person reference a document carries

    A polymorphic key holding None references nothing, and neither does an empty person-only list. The result is
    a list, not a set: the values are unvalidated and may be unhashable

    Args:
        document (dict[str, Any]): The document, or the write payload
        keys (PersonReferenceKeys): The collection's person-reference keys

    Returns:
        list[PersonReference]: One entry per referenced id, in key order
    """
    references: list[PersonReference] = []

    for key in keys.polymorphic:
        public_id: Any = document.get(key)

        if public_id is not None:
            references.append(PersonReference(key, public_id, document.get(ref_type_key(key))))

    for key in keys.person_only:
        references.extend(
            PersonReference(key, public_id, PersonReferenceType.PERSON.value)
            for public_id in _referenced_ids(document.get(key))
        )

    return references


def new_person_references(
        document: dict[str, Any],
        stored: dict[str, Any],
        keys: PersonReferenceKeys) -> list[PersonReference]:
    """
    The person references an update introduces

    A reference counts as new when the stored document does not hold the same key, id and reference type - so a
    changed id, a changed ref_type and an added list entry are all judged, and an unchanged one is not

    Args:
        document (dict[str, Any]): The update payload
        stored (dict[str, Any]): The document as currently stored
        keys (PersonReferenceKeys): The collection's person-reference keys

    Returns:
        list[PersonReference]: The payload's references the stored document does not hold
    """
    stored_references: list[PersonReference] = collect_person_references(stored, keys)

    return [
        reference for reference in collect_person_references(document, keys)
        if reference not in stored_references
    ]


def _is_public_id(value: Any) -> bool:
    """
    Answers whether a reference value can name a stored document

    Args:
        value (Any): The referenced id, as sent

    Returns:
        bool: True for an integer that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def abort_on_unknown_person_references(
        references: list[PersonReference],
        persons_manager: PersonsManager,
        person_groups_manager: PersonGroupsManager) -> None:
    """
    Refuses the request when a person reference does not resolve in the collection its reference type names

    Every reference is shape-checked first, then the ids are grouped by collection and each collection is asked
    once - at most two projected queries, however many keys reference it

    Args:
        references (list[PersonReference]): The references to resolve; nothing is queried for an empty list
        persons_manager (PersonsManager): Manager of the CmdbPersons
        person_groups_manager (PersonGroupsManager): Manager of the CmdbPersonGroups

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when a reference is not a public_id, names no known
            reference type (a null ``_ref_type`` beside a set id among them - the schema lets a null one through
            for the id-less case), or names an id its collection does not hold
    """
    ids_by_type: dict[PersonReferenceType, list[int]] = {reference_type: [] for reference_type in PersonReferenceType}

    for reference in references:
        if not _is_public_id(reference.public_id):
            abort(
                HTTPStatus.BAD_REQUEST,
                INVALID_PERSON_REFERENCE_ID_MSG.format(key=reference.key, value=reference.public_id),
            )

        if reference.reference_type not in _ALLOWED_REFERENCE_TYPES:
            abort(HTTPStatus.BAD_REQUEST, UNKNOWN_PERSON_REFERENCE_TYPE_MSG.format(
                key=reference.key, value=reference.reference_type, allowed=_ALLOWED_REFERENCE_TYPES,
            ))

        ids_by_type[PersonReferenceType(reference.reference_type)].append(reference.public_id)

    abort_on_unknown_references(persons_manager, ids_by_type[PersonReferenceType.PERSON], PERSON_LABEL)
    abort_on_unknown_references(
        person_groups_manager, ids_by_type[PersonReferenceType.PERSON_GROUP], PERSON_GROUP_LABEL,
    )


def check_person_references(references: list[PersonReference], request_user: CmdbUser) -> None:
    """
    ``abort_on_unknown_person_references`` against the request user's tenant

    The managers are only built when there is something to resolve

    Args:
        references (list[PersonReference]): The references to resolve
        request_user (CmdbUser): The user issuing the request

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for a reference that does not resolve
    """
    if not references:
        return

    persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
    person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP, request_user)

    abort_on_unknown_person_references(references, persons_manager, person_groups_manager)
