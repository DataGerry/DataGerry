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
Implementation of CmdbPerson

A CmdbPerson is one person record (collection ``management.person``). It is not a login account -
``CmdbUser`` is - but the party an ISMS document points at: a risk assessor, a risk owner, an auditor,
one of the interviewed persons, or the person responsible for implementing a control measure. Three
properties are worth knowing before changing it:

**Group membership is stored on both sides.** ``groups`` holds the public_ids of the
``CmdbPersonGroup``s this person belongs to, and each of those groups repeats the person in its
``group_members``. Neither side is derived from the other, so every write has to sync the counterpart -
that is what ``PersonsManager.update_group_in_persons`` and its twin exist for, and why deleting a
person is a cascade rather than a delete.

**The optional keys are never null.** ``phone_number`` and ``email`` default to the empty string and
``groups`` to the empty list, coerced in the constructor. The Cerberus schema types them
``string`` / ``list``; before this the model wrote null into all three, so the document it produced
could not be sent back unchanged - a GET followed by an unmodified PUT was answered
``400 Invalid data provided!``. The schema accepts null on the wire (a client that has no value for a
key may say so), the model turns it into the empty value, and ``updater_20260909`` converged the
documents already stored.

**A person referenced by ISMS is nulled out, not orphaned.** Deleting one clears the scalar reference
fields of every IsmsRiskAssessment and IsmsControlMeasureAssignment pointing at it, and pulls it out
of ``interviewed_persons`` - see ``PersonsManager.delete_with_follow_up``. ``PersonKey`` names every
persisted key and drives the shared ``from_data`` / ``to_json``
"""
from typing import Any

from cmdb.utils import coerce_empty_document_values

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.person_model.person_constants import (
    PersonKey,
    PERSON_LIST_KEYS,
    PERSON_OPTIONAL_TEXT_KEYS,
)

from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema

from cmdb.errors.models.cmdb_person import (
    CmdbPersonInitError,
    CmdbPersonInitFromDataError,
    CmdbPersonToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbPerson - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPerson(CmdbDAO):
    """
    Implementation of CmdbPerson

    Extends: CmdbDAO
    """
    COLLECTION = "management.person"

    INDEX_KEYS: list[dict[str, Any]] = [
        # The membership lookup: removing a CmdbPersonGroup pulls it out of every person that lists it
        # ('groups': group_id), which without this index is a scan of the whole collection. The twin
        # index on the other side of the pair is CmdbPersonGroup's 'group_members'
        {
            'keys': [(PersonKey.GROUPS.value, CmdbDAO.DAO_ASCENDING)],
            'name': PersonKey.GROUPS.value,
            'unique': False,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_person_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = PersonKey
    INIT_FROM_DATA_ERROR = CmdbPersonInitFromDataError
    TO_JSON_ERROR = CmdbPersonToJsonError

    # The keys the schema declares required: a document missing one is refused by the shared from_data
    # rather than turned into a half-built person whose failure surfaces somewhere else
    REQUIRED_INIT_KEYS: list[str] = [
        PersonKey.DISPLAY_NAME.value,
        PersonKey.FIRST_NAME.value,
        PersonKey.LAST_NAME.value,
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
        coerce_empty_document_values(data, PERSON_OPTIONAL_TEXT_KEYS, PERSON_LIST_KEYS)


    def __init__(
            self,
            *,
            public_id: int,
            display_name: str,
            first_name: str,
            last_name: str,
            phone_number: str | None = None,
            email: str | None = None,
            groups: list[int] | None = None) -> None:
        """
        Initialises a CmdbPerson

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        The optional values are coerced here rather than at the call sites, which is what the shared
        from_data relies on: it passes every key straight through, so the constructor is the single
        place a null from the wire or from a legacy document becomes the empty value

        Args:
            public_id (int): public_id of the CmdbPerson
            display_name (str): The display_name of the CmdbPerson
            first_name (str): first_name of the CmdbPerson
            last_name (str): last_name of the CmdbPerson
            phone_number (str, optional): phone_number of the CmdbPerson. None becomes ''
            email (str, optional): email of the CmdbPerson. None becomes ''
            groups (list[int], optional): public_id's of assigned CmdbPersonGroups. None becomes []

        Raises:
            CmdbPersonInitError: When the CmdbPerson could not be initialised
        """
        try:
            self.display_name = display_name
            self.first_name = first_name
            self.last_name = last_name
            self.phone_number = phone_number or ''
            self.email = email or ''
            self.groups = groups or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPersonInitError(err) from err
