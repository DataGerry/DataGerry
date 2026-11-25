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
Which CmdbUserGroups a CmdbType's ``acl`` block names, read from the raw block

A type's ``acl.groups.includes`` maps a CmdbUserGroup public_id - a string key - to the permissions that group
holds. These readers answer the group questions about a raw block as it is stored or sent: which groups it names,
which it grants anything, and the permissions each holds.

Every reader tolerates a missing or malformed block and a key that is no group id: it answers as if they were not
there
"""
import re
from typing import Any

from cmdb.security.acl.acl_constants import ACL_GROUP_KEY_PATTERN, AclKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'acl_group_ids', 'acl_includes', 'granting_group_ids', 'group_key_id', 'group_permissions',
]


def acl_includes(acl: Any) -> dict[str, Any]:
    """
    Answers the ``includes`` mapping of a raw ``acl`` block

    Args:
        acl (Any): The block as stored or sent

    Returns:
        dict[str, Any]: The group key -> permissions mapping; empty when the block or any level of it is missing
            or not a document
    """
    groups: Any = acl.get(AclKey.GROUPS.value) if isinstance(acl, dict) else None
    includes: Any = groups.get(AclKey.INCLUDES.value) if isinstance(groups, dict) else None

    return includes if isinstance(includes, dict) else {}


def group_key_id(key: Any) -> int | None:
    """
    Reads a group public_id out of an ``includes`` key

    A stored key is a string - the type write schema's rule (``ACL_GROUP_KEY_PATTERN``): a positive number without
    leading zeros. A section built in memory may already be keyed by the int itself

    Args:
        key (Any): The key

    Returns:
        int | None: The public_id; None for a key that is no group id
    """
    if isinstance(key, str) and re.fullmatch(ACL_GROUP_KEY_PATTERN, key):
        return int(key)

    if isinstance(key, int) and not isinstance(key, bool) and key > 0:
        return key

    return None


def acl_group_ids(acl: Any) -> list[int]:
    """
    Answers every group an ``acl`` block names, whatever it grants

    Args:
        acl (Any): The block as stored or sent

    Returns:
        list[int]: The group public_ids, sorted
    """
    return sorted({group_id for group_id in map(group_key_id, acl_includes(acl)) if group_id is not None})


def granting_group_ids(acl: Any) -> set[int]:
    """
    Answers the groups an ``acl`` block grants at least one permission

    Args:
        acl (Any): The block as stored or sent

    Returns:
        set[int]: The group public_ids whose permission list is not empty
    """
    return {
        group_id
        for key, permissions in acl_includes(acl).items()
        if (group_id := group_key_id(key)) is not None and isinstance(permissions, list) and permissions
    }


def group_permissions(acl: Any) -> dict[int, list[str]]:
    """
    Answers the permission values each group an ``acl`` block names holds, whatever the block's ``activated`` says

    Args:
        acl (Any): The block as stored or sent

    Returns:
        dict[int, list[str]]: Per group public_id, its string permission values in stored order; a key that is no
            group id is left out, a permission list that is no list holds nothing, a value that is no string is
            passed over
    """
    held: dict[int, list[str]] = {}

    for key, permissions in acl_includes(acl).items():
        group_id: int | None = group_key_id(key)

        if group_id is not None:
            listed: list[Any] = permissions if isinstance(permissions, list) else []
            held[group_id] = [permission for permission in listed if isinstance(permission, str)]

    return held
