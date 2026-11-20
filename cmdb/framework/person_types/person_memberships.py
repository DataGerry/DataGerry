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
A person's memberships changed from the person's side

Membership is stored on the group side only - a group's base field ``members`` - so a person joining or leaving a
group is a write of that group's members. Pure: a group's members, the criteria selecting the groups holding
persons, which groups a change writes, and what each group's members become
"""
from typing import Any

from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey, extract_field_value
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'group_members',
    'holding_members_criteria',
    'membership_targets',
    'members_after',
]


def group_members(document: dict[str, Any]) -> list[int]:
    """
    A person group's stored members - the person ids of its base field ``members``

    Args:
        document (dict[str, Any]): The person group object

    Returns:
        list[int]: The members in their stored order; empty when it holds none or the value is no list
    """
    members: Any = extract_field_value(document, PersonGroupField.MEMBERS.value)

    return [member for member in members if isinstance(member, int)] if isinstance(members, list) else []


def holding_members_criteria(person_ids: list[int]) -> dict[str, Any]:
    """
    Selects the objects whose base field ``members`` holds any of the persons

    Args:
        person_ids (list[int]): The persons

    Returns:
        dict[str, Any]: The criteria
    """
    return {CmdbObjectKey.FIELDS.value: {'$elemMatch': {
        CmdbObjectFieldKey.NAME.value: PersonGroupField.MEMBERS.value,
        CmdbObjectFieldKey.VALUE.value: {'$in': person_ids},
    }}}


def membership_targets(current: set[int], add: set[int], remove: set[int]) -> list[int]:
    """
    The groups a membership change has to write - a group already as asked is left alone

    Args:
        current (set[int]): The groups holding the person
        add (set[int]): The groups the person is to join
        remove (set[int]): The groups the person is to leave

    Returns:
        list[int]: The groups it joins and the groups it leaves, ascending
    """
    return sorted((add - current) | (remove & current))


def members_after(members: Any, person_id: int, join: bool) -> list[Any]:
    """
    A group's members once the person joined or left it, every other member kept in its place

    Args:
        members (Any): The stored members - a list, or nothing for a group holding none
        person_id (int): The person
        join (bool): True to add the person (at the end, once), False to take it out

    Returns:
        list[Any]: The new members
    """
    stored: list[Any] = list(members) if isinstance(members, list) else []

    if join:
        return stored if person_id in stored else [*stored, person_id]

    return [member for member in stored if member != person_id]
