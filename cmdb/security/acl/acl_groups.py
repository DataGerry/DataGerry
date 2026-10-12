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
which it grants anything, and whether one group is the only existing group it grants - the case in which deleting
that group would leave an activated list granting nobody, so the type (and its objects) could no longer be read,
edited or deleted by anyone, administrators included.

Every reader tolerates a missing or malformed block and a key that is no group id: it answers as if they were not
there
"""
import re
from typing import Any, Iterable

from cmdb.security.acl.acl_constants import ACL_GROUP_KEY_PATTERN, AclKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['acl_group_ids', 'acl_includes', 'granting_group_ids', 'is_sole_grantee']


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


def _group_id(key: Any) -> int | None:
    """
    Reads a group public_id out of an ``includes`` key

    The key rule is the type write schema's (``ACL_GROUP_KEY_PATTERN``): a positive number without leading zeros

    Args:
        key (Any): The key - a string of digits when it names a group

    Returns:
        int | None: The public_id; None for a key that is no group id
    """
    if isinstance(key, str) and re.fullmatch(ACL_GROUP_KEY_PATTERN, key):
        return int(key)

    return None


def acl_group_ids(acl: Any) -> list[int]:
    """
    Answers every group an ``acl`` block names, whatever it grants

    Args:
        acl (Any): The block as stored or sent

    Returns:
        list[int]: The group public_ids, sorted
    """
    return sorted({group_id for group_id in map(_group_id, acl_includes(acl)) if group_id is not None})


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
        if (group_id := _group_id(key)) is not None and isinstance(permissions, list) and permissions
    }


def is_sole_grantee(acl: Any, group_id: int, existing_group_ids: Iterable[int]) -> bool:
    """
    Answers whether a group is the only existing group an ACTIVATED ``acl`` block grants anything

    Then deleting the group leaves the list granting nobody - no group may read, edit or delete the type. A block
    that is not activated grants everyone, so no group is ever its sole grantee

    Args:
        acl (Any): The block as stored
        group_id (int): The group in question
        existing_group_ids (Iterable[int]): Every group that exists - a grant to a deleted group grants nobody

    Returns:
        bool: True when the block is activated, grants the group, and grants no other existing group
    """
    if not isinstance(acl, dict) or acl.get(AclKey.ACTIVATED.value) is not True:
        return False

    granting: set[int] = granting_group_ids(acl)

    if group_id not in granting:
        return False

    return not (granting - {group_id}) & set(existing_group_ids)
