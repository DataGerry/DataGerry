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
Implementation of CmdbObjectGroup in DataGerry

A CmdbObjectGroup names a set of CmdbObjects (collection ``framework.objectGroups``), so that an ISMS
document can be assessed against many objects at once: an IsmsRiskAssessment references either a single
object or one of these groups, which is what ``ObjectReferenceType`` distinguishes. Three properties
are worth knowing before changing it:

**``group_type`` decides what ``assigned_ids`` means.** STATIC holds the public_ids of the CmdbObjects
themselves; DYNAMIC holds the public_ids of CmdbTypes, and the group is every object of those types.
The two cleanup paths follow that split - deleting objects pulls their ids out of the STATIC groups
(``objects_helper``), deleting a type pulls it out of the DYNAMIC ones (``types_helper``) - so a
document whose ``group_type`` is neither is reachable by *neither* cleanup and keeps dead ids forever.
That is why the Cerberus schema constrains the key to the ``ObjectGroupMode`` members instead of
accepting any string.

**``categories`` are CmdbExtendableOptions, not CmdbCategories.** They are the options of option type
``OBJECT_GROUP`` (see ``OPTION_TYPE`` below), the free list a user maintains to file their groups
under; deleting one of those options clears it from every group that used it.

**Deleting a group deletes ISMS documents.** Every IsmsRiskAssessment that assesses this group, and
every IsmsControlMeasureAssignment belonging to those assessments, is removed with it - see
``ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade``. ``ObjectGroupKey`` names
every persisted key and drives the shared ``from_data`` / ``to_json``
"""
from typing import Any

from cmdb.utils import coerce_empty_document_values

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_group_model.object_group_constants import ObjectGroupKey, OBJECT_GROUP_LIST_KEYS
from cmdb.models.object_group_model.object_group_mode_enum import ObjectGroupMode
from cmdb.models.extendable_option_model.option_type_enum import OptionType

from cmdb.class_schema.object_group_model.cmdb_object_group_schema import get_cmdb_object_group_schema

from cmdb.errors.models.cmdb_object_group import (
    CmdbObjectGroupInitError,
    CmdbObjectGroupInitFromDataError,
    CmdbObjectGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbObjectGroup - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectGroup(CmdbDAO):
    """
    Implementation of CmdbObjectGroup

    Extends: CmdbDAO
    """
    OPTION_TYPE = OptionType.OBJECT_GROUP
    COLLECTION = "framework.objectGroups"

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(ObjectGroupKey.GROUP_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectGroupKey.GROUP_TYPE.value,
            'unique': False,
        },
        {
            'keys': [(ObjectGroupKey.ASSIGNED_IDS.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectGroupKey.ASSIGNED_IDS.value,
            'unique': False,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_object_group_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = ObjectGroupKey
    INIT_FROM_DATA_ERROR = CmdbObjectGroupInitFromDataError
    TO_JSON_ERROR = CmdbObjectGroupToJsonError

    # The keys the schema declares required: a document missing one is refused by the shared from_data
    # rather than turned into a half-built group whose failure surfaces somewhere else
    REQUIRED_INIT_KEYS: list[str] = [
        ObjectGroupKey.NAME.value,
        ObjectGroupKey.GROUP_TYPE.value,
        ObjectGroupKey.ASSIGNED_IDS.value,
    ]

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Fills the list keys of a raw document with their empty values, in place

        The hook the shared from_data runs first, and the one a route calls before inserting a
        validated payload as-is. ``assigned_ids`` is covered as a safety net only: the schema
        requires it to be a non-empty list, so a payload reaching here without one was never valid

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place
        """
        coerce_empty_document_values(data, list_keys=OBJECT_GROUP_LIST_KEYS)


    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            group_type: ObjectGroupMode,
            assigned_ids: list[int],
            categories: list[int] | None = None) -> None:
        """
        Initialises a CmdbObjectGroup

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the CmdbObjectGroup
            group_type (ObjectGroupMode): STATIC (for specific CmdbObjects) OR DYNAMIC (for CmdbTypes)
            name (str): name of the CmdbObjectGroup
            assigned_ids (list[int]): assigned public_ids of CmdbObjects or CmdbTypes, depending on
                                      group_type. Required and never empty
            categories (list[int], optional): public_ids of the assigned CmdbExtendableOptions of
                                              option type OBJECT_GROUP. None becomes []

        Raises:
            CmdbObjectGroupInitError: If initialsation failed
        """
        try:
            self.name = name
            self.group_type = group_type
            self.assigned_ids = assigned_ids
            self.categories = categories or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectGroupInitError(err) from err
