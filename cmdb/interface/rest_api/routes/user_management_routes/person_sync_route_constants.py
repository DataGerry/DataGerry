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
Constants of the person sync routes: the right, the request schemas, the answer keys and the messages
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.framework.person_sync.person_sync_constants import OnBlocked, PersonSyncKey, TypeOverrideKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PERSON_SYNC_EDIT_RIGHT',
    'ON_BLOCKED_KEY',
    'USER_SYNC_SCHEMA',
    'GROUP_SYNC_SCHEMA',
    'GroupMappingBodyKey',
    'GROUP_MAPPING_SCHEMA',
    'PersonSyncAnswerKey',
    'LeftMembersKey',
    'UserPersonKey',
    'PersonSyncMessage',
]

# The one right of the sync's configuration - every person sync route checks it
PERSON_SYNC_EDIT_RIGHT: str = 'base.user-management.sync.edit'

_ID: dict[str, Any] = {'type': 'integer', 'required': True}

# The request key choosing what a target change does with the persons that cannot move (``OnBlocked``) - not stored
ON_BLOCKED_KEY: str = 'on_blocked'

# The user sync settings, written whole, and the choice for blocked persons
USER_SYNC_SCHEMA: dict[str, Any] = {
    ON_BLOCKED_KEY: {'type': 'string', 'allowed': [choice.value for choice in OnBlocked],
                     'default': OnBlocked.CANCEL.value},
    PersonSyncKey.ACTIVE.value: {'type': 'boolean', 'required': True},
    PersonSyncKey.DEFAULT_TYPE_ID.value: {'type': 'integer', 'nullable': True, 'required': True},
    PersonSyncKey.TYPE_OVERRIDES.value: {
        'type': 'list',
        'required': True,
        'schema': {'type': 'dict', 'schema': {TypeOverrideKey.USER_ID.value: _ID, TypeOverrideKey.TYPE_ID.value: _ID}},
    },
}

# The user group sync settings: its switch
GROUP_SYNC_SCHEMA: dict[str, Any] = {
    PersonSyncKey.ACTIVE.value: {'type': 'boolean', 'required': True},
}


class GroupMappingBodyKey(BaseStrEnum):
    """
    The keys of a mapping request: an existing person group, or the Type a new one is created in
    """
    PERSON_GROUP_ID = 'person_group_id'
    TYPE_ID = 'type_id'


# One user group mapping: exactly one of the two keys
GROUP_MAPPING_SCHEMA: dict[str, Any] = {
    GroupMappingBodyKey.PERSON_GROUP_ID.value: {
        'type': 'integer', 'excludes': GroupMappingBodyKey.TYPE_ID.value, 'required': True,
    },
    GroupMappingBodyKey.TYPE_ID.value: {
        'type': 'integer', 'excludes': GroupMappingBodyKey.PERSON_GROUP_ID.value, 'required': True,
    },
}


class PersonSyncAnswerKey(BaseStrEnum):
    """
    The keys the person sync routes answer next to the settings: what a pass wrote, what a target change moved and
    copied, the group mappings, and the pre-check's relocations
    """
    CREATED = 'created'
    EDITED = 'edited'
    LEFT = 'left'
    MAPPINGS = 'mappings'
    MOVED = 'moved'
    COPIED = 'copied'
    RELOCATIONS = 'relocations'
    BLOCKED = 'blocked'


class LeftMembersKey(BaseStrEnum):
    """
    The keys of one ``left`` entry: a mapped person group and the synced persons the sync took out of it
    """
    PERSON_GROUP_ID = 'person_group_id'
    PERSON_IDS = 'person_ids'


class UserPersonKey(BaseStrEnum):
    """
    The keys of ``GET /users/<user_id>/person``: the user, its person and the person's Type - None without a person
    """
    USER_ID = 'user_id'
    PERSON_ID = 'person_id'
    TYPE_ID = 'type_id'


class PersonSyncMessage(BaseStrEnum):
    """
    The person sync routes' messages - format strings where they carry a placeholder
    """
    DUPLICATE_OVERRIDE = "Users {user_ids} carry more than one type override!"
    USER_SYNC_OFF = "The user sync is switched off - switch it on to sync!"
    USER_GROUP_NOT_FOUND = "User group {user_group_id} does not exist!"
    USER_GROUP_NOT_MAPPED = "User group {user_group_id} is mapped to no person group!"
    USER_NOT_FOUND = "User {user_id} does not exist!"
    PERSON_NOT_READABLE = "Access denied: the person of user {user_id} is in a Type you may not read!"
    MAPPING_TAKEN = "The user group or the person group is mapped already - unmap it first!"
    MAPPED_GROUP_DENIED = (
        "Access denied: mapping person group {public_id} needs READ and UPDATE on its Type {type_id}!"
    )
    MAPPED_TYPE_DENIED = "Access denied: creating the person group needs CREATE on Type {type_id}!"
    PERSONS_BLOCKED = (
        "{count} person(s) cannot move to their new Type - send on_blocked 'copy' to leave a deactivated copy and "
        "create a new person, or change nothing: {details}"
    )
    PERSON_BLOCKED = "person {person_id} of user {user_id} ({blockers})"
