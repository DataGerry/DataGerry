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
Shared constants for the CmdbRelation, CmdbObjectRelation and CmdbObjectRelationLog REST routes

Names the ACL rights guarding the routes - one enum per entity, the three of them together because
they are one family: a relation, the object relations that instantiate it, and the audit trail of
those - plus the request / response keys that belong to a route rather than to the document: the
relation-tab pagination parameters and the keys of the relation-tab instances body.

The document's own keys live with the model (``ObjectRelationKey``, ``ObjectRelationRole``,
``RelationTabKey`` in ``cmdb.models.object_relation_model``, ``ObjectRelationLogKey`` in
``cmdb.models.log_model``) because the managers read the very same keys.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DEFAULT_TAB_PAGE_SIZE',
    'MAX_TAB_PAGE_SIZE',
    'SORT_DIRECTIONS',
    'RelationRight',
    'ObjectRelationRight',
    'ObjectRelationLogRight',
    'ObjectRelationTabParam',
    'TabInstancesKey',
    'BulkDeleteKey',
    'MAX_BULK_DELETE_OBJECT_RELATIONS',
]

# Page size used when the relation-tab instances route is called without an explicit 'limit'
DEFAULT_TAB_PAGE_SIZE: int = 10

# Upper bound for that route's 'limit'. A tab can hold thousands of instances and each row costs a
# rendered counterpart, so an unbounded page is refused instead of silently served
MAX_TAB_PAGE_SIZE: int = 1000

# Sort directions accepted by the relation-tab instances route, in MongoDB's own encoding
SORT_DIRECTIONS: tuple[int, ...] = (1, -1)


# Refusals (HTTP 400) for a CmdbRelation payload that is not internally consistent. A relation
# declares every field once in its flat `fields` list and its sections only REFERENCE those names, so
# three ways of writing one make the relation unusable without anything else noticing:
#
# * a section naming a field the relation does not declare renders nothing for that entry - and, unlike
#   a CmdbType, is PROPAGATED: `get_added_and_removed_fields` reads the names out of the sections and
#   writes what it finds onto every dependent CmdbObjectRelation
# * two fields sharing one name make every read of that name ambiguous, and an ObjectRelation keys its
#   stored values by the name alone
# * two sections sharing one name collide wherever a section is addressed by it
#
# The SHAPE of both halves is `CmdbRelation.SCHEMA`'s job - a list of non-blank strings, and a known
# FieldType. These are the rules a Cerberus schema cannot express, because each spans two keys
RELATION_SECTION_FIELD_UNKNOWN_MESSAGE: str = (
    "A section can only show fields this Relation declares. Unknown in {section_name}: {unknown}. "
    "Add the fields to the Relation, or remove them from the section."
)

RELATION_DUPLICATE_FIELD_IDENTIFIER_MESSAGE: str = (
    "A field's name is its identifier and has to be unique within the Relation. Used more than once: "
    "{duplicates}."
)

RELATION_DUPLICATE_SECTION_IDENTIFIER_MESSAGE: str = (
    "A section's name is its identifier and has to be unique within the Relation. Used more than "
    "once: {duplicates}."
)

# Refusals (HTTP 400) of a CmdbObjectRelation write whose endpoints or field values do not fit its CmdbRelation.
# An endpoint the caller may not read is refused with the same message as one that does not exist, so the answer
# says nothing about objects the caller cannot see
OBJECT_RELATION_ENDPOINT_UNKNOWN_MESSAGE: str = "The {role} Object with ID:{public_id} does not exist!"
OBJECT_RELATION_TYPE_NOT_ALLOWED_MESSAGE: str = (
    "The Relation with ID:{relation_id} does not allow an Object of the Type with ID:{type_id} as its {role}!"
)
OBJECT_RELATION_FIELD_UNKNOWN_MESSAGE: str = (
    "The Relation with ID:{relation_id} declares no field(s) named: {names}!"
)
OBJECT_RELATION_FIELD_DUPLICATE_MESSAGE: str = "A field value is given more than once for: {names}!"

# The 400 of a CmdbObjectRelation write when reading its endpoints failed
OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE: str = "Failed to read the Objects of the ObjectRelation!"


class RelationRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbRelation REST routes
    """
    ADD = 'base.framework.relation.add'
    VIEW = 'base.framework.relation.view'
    EDIT = 'base.framework.relation.edit'
    DELETE = 'base.framework.relation.delete'


class ObjectRelationRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbObjectRelation REST routes
    """
    ADD = 'base.framework.objectRelation.add'
    VIEW = 'base.framework.objectRelation.view'
    EDIT = 'base.framework.objectRelation.edit'
    DELETE = 'base.framework.objectRelation.delete'


class ObjectRelationLogRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbObjectRelationLog REST routes

    Two, not four: the logs are written internally by `ObjectRelationLogsManager` whenever an
    ObjectRelation changes, so there is no route to add or edit one
    """
    VIEW = 'base.framework.objectRelationLog.view'
    DELETE = 'base.framework.objectRelationLog.delete'


class ObjectRelationTabParam(BaseStrEnum):
    """Query parameters of the relation-tab instances route"""
    RELATION_ID = 'relation_id'
    ROLE = 'role'
    LIMIT = 'limit'
    PAGE = 'page'
    SORT = 'sort'
    ORDER = 'order'


class TabInstancesKey(BaseStrEnum):
    """Keys of the relation-tab instances response body and of a single row"""
    TOTAL = 'total'
    COUNT = 'count'
    RESULTS = 'results'
    COUNTERPART = 'counterpart'


# Upper bound of one bulk delete's selection. Each id is its own atomic read-and-delete and its own history
# entry, so the selection is bounded like the port bulk routes are; the frontend sends the rows a user ticked
MAX_BULK_DELETE_OBJECT_RELATIONS: int = 5000

# Refusals of the ObjectRelation bulk delete: a body that is no object, a selection that is missing, too large or
# matches nothing (HTTP 400), and a delete that failed part-way, saying how many were deleted before it did
OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE: str = (
    "The body of a bulk delete must be a JSON object carrying '{key}'!"
)
OBJECT_RELATION_BULK_NO_IDS_MESSAGE: str = "No public_ids provided of ObjectRelations which should be deleted!"
OBJECT_RELATION_BULK_TOO_MANY_MESSAGE: str = (
    "At most {limit} ObjectRelations can be deleted at once, {count} were requested!"
)
OBJECT_RELATION_BULK_NONE_EXIST_MESSAGE: str = "No ObjectRelations exist with these IDs!"
OBJECT_RELATION_BULK_DELETE_FAILED_MESSAGE: str = (
    "Failed to delete the ObjectRelations! {deleted} of them were deleted before the failure."
)


class BulkDeleteKey(BaseStrEnum):
    """Keys of a bulk-delete request body"""
    TARGET_IDS = 'target_ids'
