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
Represents a CmdbObjectRelation in DataGerry

A CmdbObjectRelation is one *instance* of a CmdbRelation (collection ``framework.objectRelations``):
the CmdbRelation defines that, say, a server may run an application, and each CmdbObjectRelation
records one concrete pair plus the field values that relation definition declares. Four properties are
worth knowing before changing it:

**The document carries both endpoints AND both endpoint types.** ``relation_parent_type_id`` /
``relation_child_type_id`` are denormalised copies of the two objects' ``type_id``, which is what lets
a relation tab be queried without joining the objects; nothing keeps them in step if an object is
retyped, and the ``types_helper`` guard that refuses such a change is what makes that safe.

**A relation tab is exactly one (relation_id, side) group**, paged and sorted by public_id, and the two
compound indexes below exist to serve match and sort from a single index each. The single-field indexes
above them serve the cascades that clean up after a deleted object, type or relation definition.

**The two timestamps are server-owned, and they are real dates.** ``creation_time`` is stamped by the
create route and preserved by every update; ``last_edit_time`` stays null until the first edit and is
stamped by the update route. Both are declared in ``DATE_FIELDS``, so a payload's ``{'$date': ...}``
wrapper - the shape the frontend sends - is converted to a datetime before the document is stored,
whichever path writes it. Before that, ``last_edit_time`` was neither stamped nor normalised: a client
could set it on create and the wrapper was stored as a **sub-document**, which MongoDB cannot sort or
range-filter, while ``creation_time`` beside it was a real date (fixed 2026-09-08, converged by
``updater_20260910``).

**``field_values`` are name/value pairs, not the name/value/type triples a CmdbObject carries** - the
type comes from the relation definition's field, so it is not repeated per instance.
``ObjectRelationKey`` names every persisted key and drives the shared ``from_data`` / ``to_json``
"""
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.class_schema.object_relation_model.cmdb_object_relation_schema import get_cmdb_object_relation_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_relation_model.object_relation_constants import (
    OBJECT_RELATION_DATE_KEYS,
    ObjectRelationKey,
)

from cmdb.errors.models.cmdb_object_relation import (
    CmdbObjectRelationInitError,
    CmdbObjectRelationInitFromDataError,
    CmdbObjectRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbObjectRelation - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectRelation(CmdbDAO):
    """
    Implementation of a CmdbObjectRelation in DataGerry

    `Extends`: CmdbDAO
    """
    COLLECTION = "framework.objectRelations"

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(ObjectRelationKey.RELATION_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationKey.RELATION_ID.value,
            'unique': False
        },
        {
            'keys': [(ObjectRelationKey.RELATION_PARENT_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationKey.RELATION_PARENT_ID.value,
            'unique': False
        },
        {
            'keys': [(ObjectRelationKey.RELATION_PARENT_TYPE_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationKey.RELATION_PARENT_TYPE_ID.value,
            'unique': False
        },
        {
            'keys': [(ObjectRelationKey.RELATION_CHILD_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationKey.RELATION_CHILD_ID.value,
            'unique': False
        },
        {
            'keys': [(ObjectRelationKey.RELATION_CHILD_TYPE_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationKey.RELATION_CHILD_TYPE_ID.value,
            'unique': False
        },
        # A relation tab is exactly one (relation_id, side) group, paged and sorted by public_id. With
        # only the single-field indexes above MongoDB serves the match from one of them and then sorts
        # the whole group in memory; these two cover match + sort of both tabs from one index each
        {
            'keys': [
                (ObjectRelationKey.RELATION_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationKey.RELATION_PARENT_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationKey.PUBLIC_ID.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'relation_parent_tab',
            'unique': False
        },
        {
            'keys': [
                (ObjectRelationKey.RELATION_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationKey.RELATION_CHILD_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationKey.PUBLIC_ID.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'relation_child_tab',
            'unique': False
        }
    ]

    SCHEMA: dict[str, Any] = get_cmdb_object_relation_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = ObjectRelationKey
    INIT_FROM_DATA_ERROR = CmdbObjectRelationInitFromDataError
    TO_JSON_ERROR = CmdbObjectRelationToJsonError

    # Normalised to real datetimes by normalize_document, and by GenericManager on a raw dict write
    DATE_FIELDS: tuple[str, ...] = tuple(date_key.value for date_key in OBJECT_RELATION_DATE_KEYS)

    # The keys the schema declares required: a document missing one describes no relation at all, so it
    # is refused by the shared from_data rather than read as a half-built instance
    REQUIRED_INIT_KEYS: list[str] = [
        ObjectRelationKey.RELATION_ID.value,
        ObjectRelationKey.RELATION_PARENT_ID.value,
        ObjectRelationKey.RELATION_PARENT_TYPE_ID.value,
        ObjectRelationKey.RELATION_CHILD_ID.value,
        ObjectRelationKey.RELATION_CHILD_TYPE_ID.value,
    ]

    # Ten keyword arguments, one per document key - the shared from_data passes them all by name
    #pylint: disable=R0913
    def __init__(
            self,
            *,
            public_id: int,
            relation_id: int,
            relation_parent_id: int,
            relation_parent_type_id: int,
            relation_child_id: int,
            relation_child_type_id: int,
            author_id: int | None = None,
            creation_time: datetime | None = None,
            last_edit_time: datetime | None = None,
            field_values: list[dict[str, Any]] | None = None) -> None:
        """
        Initialises a CmdbObjectRelation

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of CmdbObjectRelation
            relation_id (int): public_id of the CmdbRelation
            relation_parent_id (int): public_id of the parent CmdbObject
            relation_parent_type_id (int): public_id of the parent CmdbType
            relation_child_id (int): public_id of the child CmdbObject
            relation_child_type_id (int): public_id of the child CmdbType
            author_id (int, optional): public_id of the CmdbUser who created the CmdbObjectRelation,
                                       then of the last one editing it
            creation_time (datetime, optional): When the CmdbObjectRelation was created. Stamped by the
                                                create route; never invented here, so a document that
                                                does not carry one reports None instead of "now"
            last_edit_time (datetime, optional): When the CmdbObjectRelation was last edited, or None
                                                 while it never has been
            field_values (list[dict], optional): The relation's field values as name/value pairs.
                                                 None becomes []

        Raises:
            CmdbObjectRelationInitError: If the initialisation failed
        """
        try:
            self.relation_id = relation_id
            self.relation_parent_id = relation_parent_id
            self.relation_parent_type_id = relation_parent_type_id
            self.relation_child_id = relation_child_id
            self.relation_child_type_id = relation_child_type_id
            self.author_id = author_id
            self.creation_time = creation_time
            self.last_edit_time = last_edit_time
            self.field_values = field_values or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectRelationInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises a raw document IN PLACE before the shared from_data reads it

        Turns both timestamps into real datetimes, whichever of the three shapes they arrive in - the
        ``{'$date': ...}`` wrapper the frontend sends, a timestamp string from an API client, or an
        already-normalised datetime - and fills an absent ``field_values`` with the empty list.

        A value that is present but unreadable is refused rather than guessed: the previous
        implementation parsed strings with ``fuzzy=True``, which turns a note like 'sometime in March'
        into a date built from today's day number.

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place

        Raises:
            ValueError: If a timestamp is present and cannot be read as a date
        """
        unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

        if data.get(ObjectRelationKey.FIELD_VALUES.value) is None:
            data[ObjectRelationKey.FIELD_VALUES.value] = []
