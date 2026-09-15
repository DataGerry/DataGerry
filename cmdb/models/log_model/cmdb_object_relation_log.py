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
Represents a CmdbObjectRelationLog in DataGerry

A CmdbObjectRelationLog is one entry of the object-relation audit trail (collection
``framework.objectRelationLogs``). Four properties govern any change here:

**It is append-only and written only from inside the backend.** There is no create route:
``ObjectRelationLogsManager.build_object_relation_log`` writes one whenever a CmdbObjectRelation is
created, edited or deleted, and the REST API exposes reads plus a single delete. There is therefore no
Cerberus schema either - nothing external ever hands one of these documents in - which is why
``ObjectRelationLogKey`` matters more here than elsewhere: it is the only thing keeping the writer and
the two readers spelling the nine keys the same way.

**A log outlives what it describes.** Deleting a CmdbObjectRelation writes a DELETE entry and leaves
every earlier entry in place, so the collection holds records whose ``object_relation_id`` no longer
resolves. That is the point of an audit trail, and it is why this model declares **no**
``REQUIRED_INIT_KEYS``: history must stay readable even when a record is older than a key the writer
adds later. A defect in a log is invisible by construction - nobody notices a history that quietly
lost an entry - so the model refuses nothing and invents nothing.

**Nothing is invented, including the timestamp.** The constructor used to default ``creation_time`` to
``datetime.now()``, so an entry that did not carry one reported *today*, differently on every read - on
the one collection whose whole content is "when did this happen". A document without a timestamp now
reports None. ``creation_time`` is declared in ``DATE_FIELDS``, so the value is a real date whichever
shape it was written in, and an unreadable one is refused rather than guessed (it was parsed with
``fuzzy=True``, which reads 'sometime in March' as a date built from today's day number).

**The two indexes that matter are the parent and child ones.** The only consumer - the relation-log
list in the object view - matches ``{$or: [{object_relation_parent_id}, {object_relation_child_id}]}``
and sorts by ``public_id``, so each side is covered by a compound index ending in the sort key.
``ObjectRelationLogKey`` names every persisted key and drives the shared ``from_data`` / ``to_json``
"""
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.log_model.log_interaction_enum import LogInteraction
from cmdb.models.log_model.object_relation_log_constants import (
    OBJECT_RELATION_LOG_DATE_KEYS,
    ObjectRelationLogKey,
)

from cmdb.errors.models.cmdb_object_relation_log import (
    CmdbObjectRelationLogInitError,
    CmdbObjectRelationLogInitFromDataError,
    CmdbObjectRelationLogToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbObjectRelationLog - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectRelationLog(CmdbDAO):
    """
    Implementation of a CmdbObjectRelationLog in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.objectRelationLogs'

    INDEX_KEYS: list[dict[str, Any]] = [
        # The history of one object is read as "every entry where it is either endpoint", sorted by
        # public_id. One compound index per side covers match + sort of that query from a single index;
        # without them an unbounded, append-only collection was scanned on every object view
        {
            'keys': [
                (ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationLogKey.PUBLIC_ID.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'object_relation_parent_history',
            'unique': False,
        },
        {
            'keys': [
                (ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value, CmdbDAO.DAO_ASCENDING),
                (ObjectRelationLogKey.PUBLIC_ID.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'object_relation_child_history',
            'unique': False,
        },
        # Kept although no query uses it today: the log's own delete route addresses entries by the
        # relation they belong to, and "the history of this relation" is the obvious next reader
        {
            'keys': [(ObjectRelationLogKey.OBJECT_RELATION_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': ObjectRelationLogKey.OBJECT_RELATION_ID.value,
            'unique': False,
        },
    ]

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = ObjectRelationLogKey
    INIT_FROM_DATA_ERROR = CmdbObjectRelationLogInitFromDataError
    TO_JSON_ERROR = CmdbObjectRelationLogToJsonError

    # Normalised to a real datetime by normalize_document, and by GenericManager on a raw dict write
    DATE_FIELDS: tuple[str, ...] = tuple(date_key.value for date_key in OBJECT_RELATION_LOG_DATE_KEYS)

    # Deliberately empty: see the module docstring. An audit entry is never refused for what it lacks

    #pylint: disable=R0913
    def __init__(
            self,
            *,
            public_id: int,
            object_relation_id: int,
            object_relation_parent_id: int | None = None,
            object_relation_child_id: int | None = None,
            creation_time: datetime | None = None,
            action: LogInteraction | None = None,
            author_id: int | None = None,
            author_name: str | None = None,
            changes: dict[str, Any] | None = None) -> None:
        """
        Creates an instance of CmdbObjectRelationLog

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the CmdbObjectRelationLog
            object_relation_id (int): public_id of the logged CmdbObjectRelation, which may no longer
                                      exist - a log outlives what it describes
            object_relation_parent_id (int, optional): public_id of the relation's parent CmdbObject
            object_relation_child_id (int, optional): public_id of the relation's child CmdbObject
            creation_time (datetime, optional): When the entry was written. Never invented here, so an
                                                entry that does not carry one reports None
            action (LogInteraction, optional): CREATE, EDIT or DELETE
            author_id (int, optional): public_id of the CmdbUser who made the change
            author_name (str, optional): Display name of that CmdbUser, as it was at the time
            changes (dict, optional): What changed - a flat snapshot for CREATE, a
                                      modified/added/deleted diff for EDIT, and empty for DELETE.
                                      None becomes {}, so "nothing changed" has one spelling

        Raises:
            CmdbObjectRelationLogInitError: If the CmdbObjectRelationLog could not be initialised
        """
        try:
            self.object_relation_id = object_relation_id
            self.object_relation_parent_id = object_relation_parent_id
            self.object_relation_child_id = object_relation_child_id
            self.creation_time = creation_time
            self.action = action
            self.author_id = author_id
            self.author_name = author_name
            self.changes = changes if changes is not None else {}

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectRelationLogInitError(err) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises a raw document IN PLACE before the shared from_data reads it

        Turns the timestamp into a real datetime from any of the shapes it may have been written in,
        and gives an absent ``changes`` the empty dict the log builder writes, so the document has one
        empty state rather than two.

        An unreadable timestamp is refused rather than guessed: this is the collection whose entire
        content is "when did this happen", so a plausible wrong date is the worst possible answer

        Args:
            data (dict[str, Any]): The document, edited in place

        Raises:
            ValueError: If the timestamp is present and cannot be read as a date
        """
        unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

        if data.get(ObjectRelationLogKey.CHANGES.value) is None:
            data[ObjectRelationLogKey.CHANGES.value] = {}
