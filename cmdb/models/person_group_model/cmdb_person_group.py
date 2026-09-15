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
Implementation of CmdbPersonGroup

A CmdbPersonGroup is a named set of ``CmdbPerson``s (collection ``management.personGroup``). ISMS
documents reference a group wherever they can reference a single person - a risk owner, the
responsible persons, an auditor, the party responsible for implementing a control measure - which is
what ``PersonReferenceType`` distinguishes on the referencing side. Three properties are worth knowing
before changing it:

**Membership is stored on both sides.** ``group_members`` holds the public_ids of the persons in the
group, and each of those persons repeats the group in their ``groups``. Neither side is derived from
the other, so every write has to sync the counterpart - see
``PersonGroupsManager.update_person_in_groups`` and its twin in ``PersonsManager``.

**The optional keys are never null.** ``group_members`` defaults to the empty list and ``email`` to the
empty string, coerced in the constructor. A stored ``group_members: null`` used to be reachable (the
model wrote it whenever the key was absent from the payload) and it broke two things at once: the
update route read it as ``set(None)`` and answered 500, and the Cerberus schema types the key ``list``,
so the document could not be sent back unchanged either. The schema accepts null on the wire, the
model turns it into the empty value, and ``updater_20260909`` converged the documents already stored.

**A group referenced by ISMS is nulled out, not orphaned.** Deleting one clears the reference fields of
every IsmsRiskAssessment and IsmsControlMeasureAssignment that points at it *as a group*, and removes
it from every person - see ``PersonGroupsManager.delete_with_follow_up``. ``PersonGroupKey`` names
every persisted key and drives the shared ``from_data`` / ``to_json``
"""
from typing import Any

from cmdb.utils import coerce_empty_document_values

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.person_group_model.person_group_constants import (
    PersonGroupKey,
    PERSON_GROUP_LIST_KEYS,
    PERSON_GROUP_OPTIONAL_TEXT_KEYS,
)

from cmdb.class_schema.person_group_model.cmdb_person_group_schema import get_cmdb_person_group_schema

from cmdb.errors.models.cmdb_person_group import (
    CmdbPersonGroupInitError,
    CmdbPersonGroupInitFromDataError,
    CmdbPersonGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbPersonGroup - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPersonGroup(CmdbDAO):
    """
    Implementation of CmdbPersonGroup

    Extends: CmdbDAO
    """
    COLLECTION = "management.personGroup"

    INDEX_KEYS: list[dict[str, Any]] = [
        # The membership lookup: removing a CmdbPerson pulls them out of every group that lists them
        # ('group_members': person_id). The twin index on the other side of the pair is
        # CmdbPerson's 'groups'
        {
            'keys': [(PersonGroupKey.GROUP_MEMBERS.value, CmdbDAO.DAO_ASCENDING)],
            'name': PersonGroupKey.GROUP_MEMBERS.value,
            'unique': False,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_person_group_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = PersonGroupKey
    INIT_FROM_DATA_ERROR = CmdbPersonGroupInitFromDataError
    TO_JSON_ERROR = CmdbPersonGroupToJsonError

    # The key the schema declares required: a document missing it is refused by the shared from_data
    # rather than turned into a half-built group whose failure surfaces somewhere else
    REQUIRED_INIT_KEYS: list[str] = [
        PersonGroupKey.NAME.value,
    ]

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Fills the optional keys of a raw document with their empty values, in place

        The hook the shared from_data runs first, and the one a route calls before inserting a
        validated payload as-is: both paths therefore store '' / [] rather than the null the payload
        may carry or the key it may omit

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place
        """
        coerce_empty_document_values(data, PERSON_GROUP_OPTIONAL_TEXT_KEYS, PERSON_GROUP_LIST_KEYS)


    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            group_members: list[int] | None = None,
            email: str | None = None) -> None:
        """
        Initialises a CmdbPersonGroup

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        The optional values are coerced here rather than at the call sites, which is what the shared
        from_data relies on: it passes every key straight through, so the constructor is the single
        place a null from the wire or from a legacy document becomes the empty value

        Args:
            public_id (int): public_id of the CmdbPersonGroup
            name (str): The name of the CmdbPersonGroup
            group_members (list[int], optional): public_id's of assigned CmdbPersons. None becomes []
            email (str, optional): email of the CmdbPersonGroup. None becomes ''

        Raises:
            CmdbPersonGroupInitError: When the CmdbPersonGroup could not be initialised
        """
        try:
            self.name = name
            self.group_members = group_members or []
            self.email = email or ''

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPersonGroupInitError(err) from err
