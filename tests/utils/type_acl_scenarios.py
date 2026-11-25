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
Generated type ACL scenarios for the equivalence of the type ACL and the access engine

A scenario is a set of stored Types whose ``acl`` is absent, null, switched off or switched on, granting random
permission subsets - empty lists and values that are no permission included - to random groups: the administrator
group, three other existing groups, a group that no longer exists and a key that is no group id (the write schema
refuses one, a document written around it may carry one - every reader passes it over). Seeded, so a failing
scenario is reproduced by its number
"""
import random
from itertools import combinations
from typing import Any

from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

OPERATOR_GROUP_ID: int = 9921
AUDITOR_GROUP_ID: int = 9922
GUEST_GROUP_ID: int = 9923
GONE_GROUP_ID: int = 9929
EXISTING_GROUP_IDS: tuple[int, ...] = (ADMIN_GROUP_ID, OPERATOR_GROUP_ID, AUDITOR_GROUP_ID, GUEST_GROUP_ID)
NO_GROUP_KEY: str = 'admin'
UNKNOWN_PERMISSION: str = 'READ_ALL'
PERMISSION_VALUES: list[str] = [permission.value for permission in AccessControlPermission]

# Every membership of up to three existing groups, the empty one included
USER_GROUP_SETS: list[tuple[int, ...]] = [
    members for size in range(4) for members in combinations(EXISTING_GROUP_IDS, size)
]

# Every single permission, two pairs and all four - several asked at once must all be held
PERMISSION_LISTS: list[list[AccessControlPermission]] = [
    [permission] for permission in AccessControlPermission
] + [
    [AccessControlPermission.READ, AccessControlPermission.UPDATE],
    [AccessControlPermission.READ, AccessControlPermission.CREATE],
    list(AccessControlPermission),
]

# How a Type's acl is stored, with its weight: mostly switched on, so most Types decide something
ABSENT: str = 'absent'
NULL: str = 'null'
OFF: str = 'off'
ON: str = 'on'
ACL_SHAPES: list[tuple[str, int]] = [(ABSENT, 1), (NULL, 1), (OFF, 2), (ON, 6)]

# How often a group key is named, and how often its permissions carry a value that is no permission
NAMED_PROBABILITY: float = 0.5
UNKNOWN_VALUE_PROBABILITY: float = 0.1


def scenario(number: int, type_ids: list[int]) -> list[dict[str, Any]]:
    """
    The stored Types of one scenario

    Args:
        number (int): The scenario's number - its seed
        type_ids (list[int]): The public_ids of its Types

    Returns:
        list[dict[str, Any]]: The Types, each with an acl drawn for the scenario
    """
    rng: random.Random = random.Random(number)

    return [_type(rng, type_id) for type_id in type_ids]


def _type(rng: random.Random, type_id: int) -> dict[str, Any]:
    """
    One stored Type with a drawn acl

    Args:
        rng (random.Random): The scenario's generator
        type_id (int): The Type's public_id

    Returns:
        dict[str, Any]: The Type
    """
    document: dict[str, Any] = {'public_id': type_id, 'name': f'equivalence-{type_id}', 'label': str(type_id),
                                'fields': []}
    shape: str = rng.choices([name for name, _ in ACL_SHAPES], weights=[weight for _, weight in ACL_SHAPES])[0]

    if shape == NULL:
        document['acl'] = None
    elif shape != ABSENT:
        document['acl'] = {'activated': shape == ON, 'groups': {'includes': _includes(rng)}}

    return document


def _includes(rng: random.Random) -> dict[str, list[str]]:
    """
    A drawn includes mapping: each group named or not, with a random permission subset - sometimes empty, sometimes
    with a value that is no permission

    Args:
        rng (random.Random): The scenario's generator

    Returns:
        dict[str, list[str]]: Group key -> permission values
    """
    includes: dict[str, list[str]] = {}

    for key in [str(group_id) for group_id in EXISTING_GROUP_IDS + (GONE_GROUP_ID,)] + [NO_GROUP_KEY]:
        if rng.random() < NAMED_PROBABILITY:
            values: list[str] = rng.sample(PERMISSION_VALUES, rng.randint(0, len(PERMISSION_VALUES)))

            if rng.random() < UNKNOWN_VALUE_PROBABILITY:
                values.append(UNKNOWN_PERMISSION)

            includes[key] = values

    return includes
