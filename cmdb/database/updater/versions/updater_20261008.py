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
Database update 20261008: the relation reads' two prerequisites - the default group's rights, and trustworthy
object types on every stored CmdbObjectRelation

Every object-relation read now asks for ``base.framework.objectRelation.view``, and the relation tab also reads its
CmdbRelation through ``base.framework.relation.view``. The fixed ``user`` group held neither, so a default user lost
the relation tabs. This update grants both to that group (``$addToSet``, so a group holding one already, or both,
is left as it is). A ``rights`` that is not a list is left alone - it is not a shape a group write produces, and
``updater_20261002`` repairs it.

The same reads answer a CmdbObjectRelation only when the caller may read the types of BOTH its objects, judged
by the ``relation_parent_type_id`` / ``relation_child_type_id`` stored on it. A relation written before the
create and update routes stamped those from the objects carries whatever its writer sent. This update copies each
object's live ``type_id`` onto the relation, server-side, in one aggregation that ``$merge``s back only the
relations whose stored type differs. A side whose object no longer exists keeps what it holds.

Idempotent by construction: the grant adds nothing a second time, and after the copy every stored type equals its
object's, so a second run selects nothing
"""
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped

GROUP_COLLECTION: str = 'management.groups'
OBJECT_COLLECTION: str = 'framework.objects'
OBJECT_RELATION_COLLECTION: str = 'framework.objectRelations'

PUBLIC_ID_FIELD: str = 'public_id'
RIGHTS_FIELD: str = 'rights'
TYPE_ID_FIELD: str = 'type_id'
MONGO_ID_FIELD: str = '_id'

# The fixed default group every new user joins
USER_GROUP_ID: int = 2

# The two rights the relation tab needs
GRANTED_RIGHTS: list[str] = ['base.framework.relation.view', 'base.framework.objectRelation.view']

# The fixed group, when its rights are a list a right can be added to
USER_GROUP_CRITERIA: dict[str, Any] = {PUBLIC_ID_FIELD: USER_GROUP_ID, RIGHTS_FIELD: {'$type': 'array'}}

PARENT_ID_FIELD: str = 'relation_parent_id'
CHILD_ID_FIELD: str = 'relation_child_id'
PARENT_TYPE_FIELD: str = 'relation_parent_type_id'
CHILD_TYPE_FIELD: str = 'relation_child_type_id'

# Pipeline-only fields: the joined objects and the types read from them
JOINED_PARENT_FIELD: str = 'parent_object'
JOINED_CHILD_FIELD: str = 'child_object'
LIVE_PARENT_TYPE_FIELD: str = 'live_parent_type_id'
LIVE_CHILD_TYPE_FIELD: str = 'live_child_type_id'


def build_object_type_lookup(local_field: str, as_field: str) -> dict[str, Any]:
    """
    Builds the ``$lookup`` joining one end of a relation to its object's type

    Args:
        local_field (str): The relation's key naming the object
        as_field (str): Where the joined list goes; it holds at most one type-only document

    Returns:
        dict[str, Any]: The ``$lookup`` stage
    """
    return {'$lookup': {
        'from': OBJECT_COLLECTION,
        'localField': local_field,
        'foreignField': PUBLIC_ID_FIELD,
        'pipeline': [{'$limit': 1}, {'$project': {MONGO_ID_FIELD: 0, TYPE_ID_FIELD: 1}}],
        'as': as_field,
    }}


def live_type_or_stored(joined_field: str, stored_field: str) -> dict[str, Any]:
    """
    Builds the expression answering the joined object's type, or the stored one when the object is gone

    Args:
        joined_field (str): The joined object list
        stored_field (str): The type stored on the relation

    Returns:
        dict[str, Any]: The expression
    """
    return {'$ifNull': [{'$arrayElemAt': [f'${joined_field}.{TYPE_ID_FIELD}', 0]}, f'${stored_field}']}


def build_type_restamp_pipeline() -> list[dict[str, Any]]:
    """
    Builds the aggregation copying each object's live type onto every relation whose stored type differs

    Runs over the object relations and writes back into them (``$merge`` on ``_id``, existing documents only), so
    no relation leaves the server

    Returns:
        list[dict[str, Any]]: The aggregation pipeline
    """
    return [
        build_object_type_lookup(PARENT_ID_FIELD, JOINED_PARENT_FIELD),
        build_object_type_lookup(CHILD_ID_FIELD, JOINED_CHILD_FIELD),
        {'$addFields': {
            LIVE_PARENT_TYPE_FIELD: live_type_or_stored(JOINED_PARENT_FIELD, PARENT_TYPE_FIELD),
            LIVE_CHILD_TYPE_FIELD: live_type_or_stored(JOINED_CHILD_FIELD, CHILD_TYPE_FIELD),
        }},
        {'$match': {'$expr': {'$or': [
            {'$ne': [f'${LIVE_PARENT_TYPE_FIELD}', f'${PARENT_TYPE_FIELD}']},
            {'$ne': [f'${LIVE_CHILD_TYPE_FIELD}', f'${CHILD_TYPE_FIELD}']},
        ]}}},
        {'$project': {
            MONGO_ID_FIELD: 1,
            PARENT_TYPE_FIELD: f'${LIVE_PARENT_TYPE_FIELD}',
            CHILD_TYPE_FIELD: f'${LIVE_CHILD_TYPE_FIELD}',
        }},
        {'$merge': {
            'into': OBJECT_RELATION_COLLECTION,
            'on': MONGO_ID_FIELD,
            'whenMatched': 'merge',
            'whenNotMatched': 'discard',
        }},
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261008 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261008(BaseDatabaseUpdate):
    """
    Grants the default group the two relation view rights, and copies each object's live type onto every stored
    CmdbObjectRelation

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261008


    def description(self) -> str:
        return "Grants the 'user' group the relation view rights and re-stamps the object relations' object types"


    def start_update(self) -> None:
        """
        Grants the rights, re-stamps the relations, then bumps the version

        Raises:
            UpdaterException: If a read or a write failed
        """
        try:
            self.dbm.update_many_raw(
                collection=GROUP_COLLECTION,
                db_name=self.db_name,
                filter_query=USER_GROUP_CRITERIA,
                update={'$addToSet': {RIGHTS_FIELD: {'$each': GRANTED_RIGHTS}}},
            )

            # Consumed so the $merge runs to its end before the version is bumped
            list(self.dbm.aggregate(OBJECT_RELATION_COLLECTION, self.db_name, build_type_restamp_pipeline()))

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
