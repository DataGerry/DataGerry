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
The rules person sync settings must pass before they are stored

**Every target Type is one the sync can write into**, whether the sync is on or not - an override chosen while it is
off is used the moment it is switched on. A target exists, carries PERSON, is active (a deactivated Type's objects
cannot be written) and requires no field the sync cannot always fill: the sync fills the display name for every user,
the first name, last name and email only when the user has them. A required field with a usable default is fine, and
a field of a multi-data section never is a problem - the sync writes no rows.

**The user sync is switched on with a default Type** - and so only while a Type carries PERSON. An override names an
existing user.

**The user group sync needs the user sync** (its members are the user sync's persons) and a Type carrying
PERSON_GROUP. Switching the user sync off switches it off too (``sync_settings.switch_user_sync_off``).

The checks are pure; ``find_sync_settings_problems`` reads what they need - the target Types, the override users and
whether a PERSON_GROUP Type exists - with one query each, and answers every problem at once
"""
from typing import Any

from cmdb.manager import TypesManager, UsersManager
from cmdb.models.type_model import CmdbType, FieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.framework.object_field_defaults import usable_default
from cmdb.framework.object_field_value_rules import FieldValueRule, PatternBudget, build_field_value_rules
from cmdb.framework.object_required_fields import collect_required_field_names, mds_section_field_names
from cmdb.framework.person_sync.person_sync_constants import SYNC_FILLED_PERSON_FIELDS, PersonSyncProblem
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings

from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'unfillable_field_names',
    'unfillable_required_fields',
    'target_type_problems',
    'usable_target_type',
    'user_sync_problems',
    'group_sync_problems',
    'find_sync_settings_problems',
]


def unfillable_field_names(type_fields: list[dict[str, Any]], in_rows: set[str] | None = None,
                           filled: frozenset[str] = SYNC_FILLED_PERSON_FIELDS) -> list[str]:
    """
    Names the required fields among these definitions the sync cannot always fill

    A field the sync fills for every record is fine, so is one with a usable default; a field of a multi-data section
    (``in_rows``) is never judged - the sync writes no rows

    Args:
        type_fields (list[dict[str, Any]]): Field definitions - a Type's, or a section template's
        in_rows (set[str] | None): The names among them that live in a multi-data section; None for none
        filled (frozenset[str]): The fields the sync fills for every record - a person's by default

    Returns:
        list[str]: The field names, sorted; empty when the sync can fill every required field
    """
    required: set[str] = collect_required_field_names(type_fields)
    rows: set[str] = in_rows or set()
    rules: dict[str, FieldValueRule] = build_field_value_rules(type_fields)
    budget: PatternBudget = PatternBudget()
    unfillable: list[str] = []

    for type_field in type_fields:
        name: Any = type_field.get(FieldKey.NAME.value)

        if name not in required or name in filled or name in rows:
            continue

        if usable_default(type_field, rules.get(name), budget) is None:
            unfillable.append(name)

    return sorted(unfillable)


def unfillable_required_fields(type_instance: CmdbType,
                               filled: frozenset[str] = SYNC_FILLED_PERSON_FIELDS) -> list[str]:
    """
    Names the required fields of a target Type the sync cannot always fill (``unfillable_field_names``)

    Args:
        type_instance (CmdbType): The target Type
        filled (frozenset[str]): The fields the sync fills for every record - a person's by default

    Returns:
        list[str]: The field names, sorted; empty when the sync can fill every required field
    """
    in_rows: set[str] = {name for names in mds_section_field_names(type_instance).values() for name in names}

    return unfillable_field_names(type_instance.get_fields() or [], in_rows, filled)


def target_type_problems(type_id: int, type_instance: CmdbType | None) -> list[str]:
    """
    Judges one target Type: it exists, carries PERSON, is active and requires nothing the sync cannot fill

    Args:
        type_id (int): The chosen Type's id
        type_instance (CmdbType | None): The stored Type, None when there is none

    Returns:
        list[str]: The problems; a missing Type has only that one
    """
    if type_instance is None:
        return [PersonSyncProblem.TYPE_MISSING.value.format(type_id=type_id)]

    if type_instance.special_type != SpecialType.PERSON.value:
        return [PersonSyncProblem.TYPE_NOT_PERSON.value.format(type_id=type_id)]

    problems: list[str] = []

    if not type_instance.active:
        problems.append(PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=type_id))

    if unfillable := unfillable_required_fields(type_instance):
        problems.append(PersonSyncProblem.TYPE_UNFILLABLE_FIELDS.value.format(type_id=type_id, names=unfillable))

    return problems


def usable_target_type(type_id: int | None, type_instance: CmdbType | None) -> CmdbType:
    """
    Answers a Type the sync writes a person into, refusing one it cannot write into

    Args:
        type_id (int | None): The Type's id; None when no target is chosen
        type_instance (CmdbType | None): The stored Type, None when there is none

    Raises:
        PersonSyncTargetError: When no Type is chosen, it is gone or it is no longer usable

    Returns:
        CmdbType: The Type
    """
    if type_instance is None:
        raise PersonSyncTargetError(f"The user sync's target Type {type_id} does not exist!")

    if problems := target_type_problems(type_id, type_instance):
        raise PersonSyncTargetError(' '.join(problems))

    return type_instance


def user_sync_problems(users: UserSyncSettings, types: dict[int, CmdbType], existing_user_ids: set[int]) -> list[str]:
    """
    Judges the user sync: a default Type to switch it on, usable targets, existing override users

    Args:
        users (UserSyncSettings): The user sync's settings
        types (dict[int, CmdbType]): The stored target Types by id; a missing id is a missing Type
        existing_user_ids (set[int]): The override users that exist

    Returns:
        list[str]: The problems, targets in id order, then users in id order
    """
    problems: list[str] = []

    if users.active and users.default_type_id is None:
        problems.append(PersonSyncProblem.NO_DEFAULT_TYPE.value)

    for type_id in sorted(users.target_type_ids()):
        problems.extend(target_type_problems(type_id, types.get(type_id)))

    for user_id in sorted(users.type_overrides):
        if user_id not in existing_user_ids:
            problems.append(PersonSyncProblem.OVERRIDE_USER_MISSING.value.format(user_id=user_id))

    return problems


def group_sync_problems(users: UserSyncSettings,
                        groups: GroupSyncSettings,
                        person_group_type_exists: bool) -> list[str]:
    """
    Judges the user group sync: switched on only with the user sync and a Type carrying PERSON_GROUP

    Args:
        users (UserSyncSettings): The user sync's settings
        groups (GroupSyncSettings): The user group sync's settings
        person_group_type_exists (bool): Whether a Type carries PERSON_GROUP

    Returns:
        list[str]: The problems; none while the group sync is off
    """
    if not groups.active:
        return []

    problems: list[str] = []

    if not users.active:
        problems.append(PersonSyncProblem.GROUPS_WITHOUT_USERS.value)

    if not person_group_type_exists:
        problems.append(PersonSyncProblem.NO_PERSON_GROUP_TYPE.value)

    return problems


def find_sync_settings_problems(settings: PersonSyncSettings,
                                types_manager: TypesManager,
                                users_manager: UsersManager) -> list[str]:
    """
    Judges person sync settings before they are stored, reading what the rules need

    One read of the target Types, one of the override users (only when there are overrides), one existence check of
    a PERSON_GROUP Type (only when the group sync is switched on)

    Args:
        settings (PersonSyncSettings): The settings to store
        types_manager (TypesManager): Reads the Types
        users_manager (UsersManager): Reads the users

    Raises:
        TypesManagerGetError / UsersManagerGetError: When a read fails - the database's failure, not the settings'

    Returns:
        list[str]: Every problem, the user sync's first; empty when the settings may be stored
    """
    target_ids: list[int] = sorted(settings.users.target_type_ids())
    types: dict[int, CmdbType] = types_manager.get_types_lookup(target_ids)
    override_user_ids: list[int] = sorted(settings.users.type_overrides)
    existing_user_ids: set[int] = (
        set(users_manager.get_user_lookup(override_user_ids)) if override_user_ids else set()
    )
    person_group_type_exists: bool = (
        settings.groups.active and types_manager.check_special_type_exists(SpecialType.PERSON_GROUP)
    )

    return (
        user_sync_problems(settings.users, types, existing_user_ids)
        + group_sync_problems(settings.users, settings.groups, person_group_type_exists)
    )
