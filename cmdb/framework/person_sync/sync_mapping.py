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
What the sync writes: a user's values on its person, a user group's name on its person group, the synced members

Pure - no database: the sync engine reads the users, groups and objects and hands them in.

**A person's synced values come from its user.** The display name is the user's (its full name, else its user name),
so it always has a value; first name, last name and email are the user's, or empty. Only what a person and a user
share is copied - never a password, an API level or a token. An optional value the target Type's own rules refuse
(the text cap, a field's pattern - the email pattern above all) is written empty rather than failing the write; the
display name is never emptied - a Type whose rules refuse it fails that one write, which names the field. The person
is active exactly while its user is.

**A fingerprint of the synced values decides whether a person needs a write.** The same values and active state give
the same fingerprint, whichever order they were built in.

**A mapped person group's members are the persons of the user group's users**, in id order. The persons added by hand
- any member that is not a synced person - are kept ahead of them, in their stored order
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.person_type_constants import PersonField

from cmdb.framework.object_field_value_rules import FieldValueRule, PatternBudget, find_value_errors
from cmdb.framework.person_sync.person_sync_constants import (
    EMPTY_SYNCED_VALUE,
    OPTIONAL_SYNCED_PERSON_FIELDS,
    SyncFingerprintKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SyncedPerson',
    'synced_person_from_user',
    'sync_fingerprint',
    'person_group_name',
    'persons_of_users',
    'synced_member_ids',
    'merge_group_members',
]


@dataclass(frozen=True)
class SyncedPerson:
    """
    What the sync writes on one user's person

    Attributes:
        values (dict[str, str]): field name -> value, for every synced field (``SYNCED_PERSON_FIELDS``)
        active (bool): The person's active state - its user's
    """
    values: dict[str, str]
    active: bool


    def fingerprint(self) -> str:
        """
        Returns the fingerprint of these values and this active state - what ``sync_hash`` stores

        Returns:
            str: The hex digest
        """
        return sync_fingerprint({
            SyncFingerprintKey.VALUES.value: self.values,
            SyncFingerprintKey.ACTIVE.value: self.active,
        })


def _accepted_or_empty(name: str, value: str, rule: FieldValueRule | None, budget: PatternBudget) -> str:
    """
    Keeps an optional synced value the target field accepts, empties one it refuses

    Args:
        name (str): The field name
        value (str): The user's value
        rule (FieldValueRule | None): The target field's value rule; None when it has none
        budget (PatternBudget): The person's pattern time budget

    Returns:
        str: The value, or the empty value
    """
    if value == EMPTY_SYNCED_VALUE or rule is None:
        return value

    return EMPTY_SYNCED_VALUE if find_value_errors(name, value, rule, budget) else value


def synced_person_from_user(user: CmdbUser, rules: dict[str, FieldValueRule]) -> SyncedPerson:
    """
    Builds what the sync writes on a user's person

    Args:
        user (CmdbUser): The user
        rules (dict[str, FieldValueRule]): The target Type's value rules by field name
            (``object_field_value_rules.build_field_value_rules``)

    Returns:
        SyncedPerson: The synced values and the active state
    """
    budget: PatternBudget = PatternBudget()
    optional: dict[str, str] = {
        PersonField.FIRST_NAME.value: user.first_name or EMPTY_SYNCED_VALUE,
        PersonField.LAST_NAME.value: user.last_name or EMPTY_SYNCED_VALUE,
        PersonField.EMAIL.value: user.email or EMPTY_SYNCED_VALUE,
    }
    values: dict[str, str] = {PersonField.DISPLAY_NAME.value: user.get_display_name()}

    for name in OPTIONAL_SYNCED_PERSON_FIELDS:
        values[name] = _accepted_or_empty(name, optional[name], rules.get(name), budget)

    return SyncedPerson(values=values, active=user.active is True)


def sync_fingerprint(payload: dict[str, Any]) -> str:
    """
    Fingerprints what the sync wrote, independent of key order

    Args:
        payload (dict[str, Any]): JSON-serialisable values

    Returns:
        str: The SHA-256 hex digest of the payload's canonical JSON
    """
    canonical: str = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def person_group_name(user_group: CmdbUserGroup) -> str:
    """
    Returns the name a mapped person group carries: its user group's label, else its name

    Args:
        user_group (CmdbUserGroup): The mapped user group

    Returns:
        str: The person group's name
    """
    return user_group.label or user_group.name


def persons_of_users(user_ids: list[int], person_id_by_user: dict[int, int]) -> list[int]:
    """
    Returns the persons of the given users - a user without a person yet is left out

    Args:
        user_ids (list[int]): The users
        person_id_by_user (dict[int, int]): user id -> the id of the user's person

    Returns:
        list[int]: The person ids, ascending
    """
    return sorted(person_id_by_user[user_id] for user_id in user_ids if user_id in person_id_by_user)


def synced_member_ids(user_group_id: int,
                      group_ids_by_user: dict[int, list[int]],
                      person_id_by_user: dict[int, int]) -> list[int]:
    """
    Returns the persons a mapped person group holds for its user group: its users' persons

    A user without a person yet is left out; the next pass that creates it adds it

    Args:
        user_group_id (int): The mapped user group
        group_ids_by_user (dict[int, list[int]]): user id -> the user's group ids
        person_id_by_user (dict[int, int]): user id -> the id of the user's person

    Returns:
        list[int]: The person ids, ascending
    """
    return persons_of_users(
        [user_id for user_id, group_ids in group_ids_by_user.items() if user_group_id in group_ids], person_id_by_user,
    )


def merge_group_members(stored_members: list[int],
                        synced_person_ids: set[int],
                        synced_members: list[int]) -> list[int]:
    """
    Builds a mapped person group's members: the persons added by hand, then the synced members

    Every synced person in a mapped group is the sync's, so a stored synced person the group no longer holds for its
    user group leaves; any other member was added by hand and stays, in its stored order

    Args:
        stored_members (list[int]): The group's stored members
        synced_person_ids (set[int]): The ids of every synced person
        synced_members (list[int]): The members the user group gives it (``synced_member_ids``)

    Returns:
        list[int]: The members to store, each once
    """
    kept: list[int] = list(dict.fromkeys(
        member for member in stored_members if member not in synced_person_ids
    ))
    kept_ids: set[int] = set(kept)

    return kept + [member for member in dict.fromkeys(synced_members) if member not in kept_ids]
