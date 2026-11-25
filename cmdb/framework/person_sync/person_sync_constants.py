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
Constants of the user -> person sync: its settings section, the section's keys and the refusals of its rules
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectSystemRefKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PERSON_SYNC_SETTINGS_SECTION',
    'PersonSyncKey',
    'TypeOverrideKey',
    'SYNC_FILLED_PERSON_FIELDS',
    'SYNCED_PERSON_FIELDS',
    'OPTIONAL_SYNCED_PERSON_FIELDS',
    'EMPTY_SYNCED_VALUE',
    'SyncFingerprintKey',
    'PersonSyncProblem',
    'SyncLockProblem',
    'SyncGuardProblem',
    'PERSON_GROUP_FILLED_FIELDS',
    'GroupMappingKey',
    'GroupMappingProblem',
    'RelocationBlocker',
    'RelocationKey',
    'OnBlocked',
    'RELOCATION_REFERENCE_KINDS',
    'KIND_PATH',
    'ID_PATH',
]

# The settings.conf section holding both syncs' settings - its document's _id
PERSON_SYNC_SETTINGS_SECTION: str = 'person_sync'


class PersonSyncKey(BaseStrEnum):
    """
    The keys of the person sync settings section

    USERS and GROUPS hold the two syncs; ACTIVE is each one's switch; DEFAULT_TYPE_ID is the PERSON Type every user
    is mirrored into, TYPE_OVERRIDES the users mirrored into another one (``TypeOverrideKey`` entries)
    """
    USERS = 'users'
    GROUPS = 'groups'
    ACTIVE = 'active'
    DEFAULT_TYPE_ID = 'default_type_id'
    TYPE_OVERRIDES = 'type_overrides'


class TypeOverrideKey(BaseStrEnum):
    """
    The keys of one entry of ``type_overrides``: the user and the PERSON Type its person lives in

    A list of entries rather than a map keyed by the user id: a stored key is a string, and a list lets one query
    ask whether a Type is any user's target
    """
    USER_ID = 'user_id'
    TYPE_ID = 'type_id'


# The person fields the sync fills for every user: a user may carry no first name, last name or email, but always has
# a display name. A target Type's required field outside this set, without a usable default, could not be filled
SYNC_FILLED_PERSON_FIELDS: frozenset[str] = frozenset({PersonField.DISPLAY_NAME.value})

# The person fields the sync writes from a user, in this order; phone_number is the person's own
SYNCED_PERSON_FIELDS: tuple[str, ...] = (
    PersonField.DISPLAY_NAME.value,
    PersonField.FIRST_NAME.value,
    PersonField.LAST_NAME.value,
    PersonField.EMAIL.value,
)

# The synced fields a user may leave empty - and that are written empty when the target Type's rules refuse the value
OPTIONAL_SYNCED_PERSON_FIELDS: tuple[str, ...] = tuple(
    name for name in SYNCED_PERSON_FIELDS if name not in SYNC_FILLED_PERSON_FIELDS
)

# What an empty synced text field holds
EMPTY_SYNCED_VALUE: str = ''


class SyncFingerprintKey(BaseStrEnum):
    """
    The keys of what a synced person's fingerprint is computed over: the synced field values and the active state
    """
    VALUES = 'values'
    ACTIVE = 'active'


class PersonSyncProblem(BaseStrEnum):
    """
    Why a person sync setting is refused - each a format string, joined into one 400 by the caller
    """
    NO_DEFAULT_TYPE = "The user sync needs a default person Type before it can be switched on!"
    TYPE_MISSING = "Type {type_id} does not exist!"
    TYPE_NOT_PERSON = "Type {type_id} does not carry the PERSON marker!"
    TYPE_INACTIVE = "Type {type_id} is deactivated - its objects cannot be written!"
    TYPE_UNFILLABLE_FIELDS = (
        "Type {type_id} requires field(s) the sync cannot always fill: {names} - remove the flag or give them a "
        "default value!"
    )
    OVERRIDE_USER_MISSING = "User {user_id} does not exist!"
    GROUPS_WITHOUT_USERS = "The user group sync needs the user sync to be switched on!"
    NO_DEFAULT_GROUP_TYPE = "The user group sync needs a default person group Type before it can be switched on!"


class SyncLockProblem(BaseStrEnum):
    """
    Why a write to a synced object is refused - each a format string, joined into one 400 by the caller
    """
    PERSON_FIELDS = (
        "Object {public_id} mirrors user {user_id}: its field(s) {names} change only when the user changes!"
    )
    PERSON_ACTIVE = "Object {public_id} mirrors user {user_id}: it is active exactly while the user is!"
    TYPE = "Object {public_id} is synced from user management and keeps its Type!"
    GROUP_NAME = "Object {public_id} mirrors user group {group_id}: its name changes only when the user group's does!"
    GROUP_MEMBERS = (
        "Object {public_id} mirrors user group {group_id}: its synced members change only when a user joins or leaves "
        "the user group - added {added}, removed {removed}!"
    )


class SyncGuardProblem(BaseStrEnum):
    """
    Why a delete or a Type change is refused for the sync's sake - each a format string
    """
    SYNCED_PERSON_DELETE = (
        "Object {public_id} mirrors user {user_id} and cannot be deleted while it is linked - it goes when the user "
        "does!"
    )
    MAPPED_GROUP_DELETE = (
        "Object {public_id} mirrors user group {group_id} and cannot be deleted while the user group sync is on!"
    )
    TARGET_TYPE_DELETE = "Type {type_id} is a target of the user sync and cannot be deleted - choose another first!"
    TARGET_TYPE_CHANGE = (
        "Type {type_id} is a target of the user sync or holds a synced person, and must stay one the sync can write "
        "into: {problems}"
    )
    TARGET_TEMPLATE_CHANGE = (
        "Section template '{name}' is used by Type(s) {type_ids} the user sync writes into, which would then require "
        "field(s) the sync cannot always fill: {names} - remove the flag or give them a default value!"
    )
    GROUP_DEFAULT_TYPE_DELETE = (
        "Type {type_id} is the user group sync's default Type and cannot be deleted - choose another first!"
    )
    GROUP_DEFAULT_TYPE_CHANGE = (
        "Type {type_id} is the user group sync's default Type and must stay one it can create person groups in: "
        "{problems}"
    )
    GROUP_DEFAULT_TEMPLATE_CHANGE = (
        "Section template '{name}' is used by the user group sync's default Type {type_id}, which would then require "
        "field(s) the sync cannot fill: {names} - remove the flag or give them a default value!"
    )


# The person group fields the sync fills for every mapped person group it creates
PERSON_GROUP_FILLED_FIELDS: frozenset[str] = frozenset({PersonGroupField.NAME.value, PersonGroupField.MEMBERS.value})


class GroupMappingKey(BaseStrEnum):
    """
    The keys of one user group mapping: the user group and the person group mirroring it
    """
    USER_GROUP_ID = 'user_group_id'
    PERSON_GROUP_ID = 'person_group_id'


class GroupMappingProblem(BaseStrEnum):
    """
    Why mapping a user group is refused - each a format string, joined into one 400 by the caller
    """
    OBJECT_MISSING = "Object {public_id} does not exist!"
    NOT_PERSON_GROUP = "Object {public_id} is no person group!"
    PERSON_GROUP_MAPPED = "Person group {public_id} mirrors user group {user_group_id} already!"
    PERSON_GROUP_INACTIVE = "Person group {public_id} is deactivated - activate it before mapping it!"
    TYPE_NOT_PERSON_GROUP = "Type {type_id} does not carry the PERSON_GROUP marker!"


class RelocationBlocker(BaseStrEnum):
    """
    Why a synced person cannot move to its new target Type - each a format string
    """
    LOST_FIELDS = "it holds values of field(s) {names} that Type {type_id} does not declare with the same kind"
    LOST_SECTIONS = "it holds rows of multi-data section(s) {names} that Type {type_id} does not declare"
    REFERENCE_FIELD = "object {holder_id} references it in field '{name}', which allows only Type(s) {type_ids}"
    REFERENCE_SECTION = "object {holder_id} shows its values in reference section field '{name}'"
    RELATION_SIDE = "object relation {relation_id}: relation {definition_id} allows only Type(s) {type_ids} as {side}"
    LOCATION = "it is placed in the location tree"


class RelocationKey(BaseStrEnum):
    """
    The keys of one person's relocation, as the pre-check answers it
    """
    USER_ID = 'user_id'
    PERSON_ID = 'person_id'
    FROM_TYPE_ID = 'from_type_id'
    TO_TYPE_ID = 'to_type_id'
    BLOCKERS = 'blockers'


class OnBlocked(BaseStrEnum):
    """
    What a target change does with the persons that cannot move: refuse the change, or leave a deactivated copy in the
    old Type and create a new person in the new one
    """
    CANCEL = 'cancel'
    COPY = 'copy'


# The field kinds whose value is another object's id, limited to the Types the field allows
RELOCATION_REFERENCE_KINDS: tuple[str, ...] = (FieldType.REFERENCE.value, FieldType.REF_SECTION.value)


# The paths of a linked object's link, for queries
KIND_PATH: str = f'{CmdbObjectKey.SYSTEM_REF.value}.{CmdbObjectSystemRefKey.KIND.value}'
ID_PATH: str = f'{CmdbObjectKey.SYSTEM_REF.value}.{CmdbObjectSystemRefKey.ID.value}'
