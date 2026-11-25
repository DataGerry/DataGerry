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
The person sync settings: one ``settings.conf`` section holding the user sync and the user group sync

A system without the section has both syncs off and no targets - a fresh installation never chooses a Type for the
admin. The section is written whole: both halves are set on every write, so a stored half never outlives a change
of the other. The rules a write must pass are ``sync_settings_rules``'s
"""
from dataclasses import dataclass, field, replace
from typing import Any

from cmdb.manager import SettingsManager

from cmdb.framework.write_ledger import WriteLedger

from cmdb.framework.person_sync.person_sync_constants import (
    PERSON_SYNC_SETTINGS_SECTION,
    PersonSyncKey,
    TypeOverrideKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'UserSyncSettings',
    'GroupSyncSettings',
    'PersonSyncSettings',
    'settings_from_document',
    'settings_to_document',
    'read_sync_settings',
    'write_sync_settings',
    'switch_user_sync_off',
    'drop_type_override',
]


@dataclass(frozen=True)
class UserSyncSettings:
    """
    The user sync: its switch, the PERSON Type every user is mirrored into, and the users mirrored into another one

    Attributes:
        active (bool): Whether users are mirrored into persons
        default_type_id (int | None): The PERSON Type of every user without an override; None until one is chosen
        type_overrides (dict[int, int]): user id -> the PERSON Type that user's person lives in
    """
    active: bool = False
    default_type_id: int | None = None
    type_overrides: dict[int, int] = field(default_factory=dict)


    def target_type_ids(self) -> set[int]:
        """
        Returns every PERSON Type the user sync writes into: the default and each override

        Returns:
            set[int]: The target Type ids; empty while none is chosen
        """
        targets: set[int] = set(self.type_overrides.values())

        if self.default_type_id is not None:
            targets.add(self.default_type_id)

        return targets


@dataclass(frozen=True)
class GroupSyncSettings:
    """
    The user group sync: its switch and the PERSON_GROUP Type every user group's person group is created in. Which user
    group a person group mirrors is stored on the person group object

    Attributes:
        active (bool): Whether user groups are mirrored into their person groups
        default_type_id (int | None): The PERSON_GROUP Type a user group's person group is created in; None until one
            is chosen. A change applies to person groups created afterwards - the existing ones stay where they are
    """
    active: bool = False
    default_type_id: int | None = None


@dataclass(frozen=True)
class PersonSyncSettings:
    """
    Both syncs' settings, as one section stores them

    Attributes:
        users (UserSyncSettings): The user sync
        groups (GroupSyncSettings): The user group sync
    """
    users: UserSyncSettings = field(default_factory=UserSyncSettings)
    groups: GroupSyncSettings = field(default_factory=GroupSyncSettings)


def _overrides_from_entries(entries: Any) -> dict[int, int]:
    """
    Reads the stored ``type_overrides`` entries into user id -> Type id

    Args:
        entries (Any): The stored list of ``{user_id, type_id}`` entries; anything else reads as no override

    Returns:
        dict[int, int]: The overrides
    """
    if not isinstance(entries, list):
        return {}

    return {
        entry[TypeOverrideKey.USER_ID.value]: entry[TypeOverrideKey.TYPE_ID.value]
        for entry in entries
        if isinstance(entry, dict) and TypeOverrideKey.USER_ID.value in entry and TypeOverrideKey.TYPE_ID.value in entry
    }


def settings_from_document(document: dict[str, Any] | None) -> PersonSyncSettings:
    """
    Reads the stored section into the settings; a missing section or key reads as off and unchosen

    Args:
        document (dict[str, Any] | None): The stored section, None when there is none

    Returns:
        PersonSyncSettings: The settings
    """
    stored: dict[str, Any] = document or {}
    users: dict[str, Any] = stored.get(PersonSyncKey.USERS.value) or {}
    groups: dict[str, Any] = stored.get(PersonSyncKey.GROUPS.value) or {}

    return PersonSyncSettings(
        users=UserSyncSettings(
            active=users.get(PersonSyncKey.ACTIVE.value) is True,
            default_type_id=users.get(PersonSyncKey.DEFAULT_TYPE_ID.value),
            type_overrides=_overrides_from_entries(users.get(PersonSyncKey.TYPE_OVERRIDES.value)),
        ),
        groups=GroupSyncSettings(active=groups.get(PersonSyncKey.ACTIVE.value) is True,
                                 default_type_id=groups.get(PersonSyncKey.DEFAULT_TYPE_ID.value)),
    )


def settings_to_document(settings: PersonSyncSettings) -> dict[str, Any]:
    """
    Builds the section's values from the settings - both halves, the overrides in user id order

    Args:
        settings (PersonSyncSettings): The settings

    Returns:
        dict[str, Any]: The values to store under the section's _id
    """
    return {
        PersonSyncKey.USERS.value: {
            PersonSyncKey.ACTIVE.value: settings.users.active,
            PersonSyncKey.DEFAULT_TYPE_ID.value: settings.users.default_type_id,
            PersonSyncKey.TYPE_OVERRIDES.value: [
                {TypeOverrideKey.USER_ID.value: user_id, TypeOverrideKey.TYPE_ID.value: type_id}
                for user_id, type_id in sorted(settings.users.type_overrides.items())
            ],
        },
        PersonSyncKey.GROUPS.value: {
            PersonSyncKey.ACTIVE.value: settings.groups.active,
            PersonSyncKey.DEFAULT_TYPE_ID.value: settings.groups.default_type_id,
        },
    }


def read_sync_settings(settings_manager: SettingsManager) -> PersonSyncSettings:
    """
    Reads the stored person sync settings

    Args:
        settings_manager (SettingsManager): The tenant's settings

    Returns:
        PersonSyncSettings: The settings; both syncs off when the section was never written
    """
    return settings_from_document(settings_manager.get_section(PERSON_SYNC_SETTINGS_SECTION))


def write_sync_settings(settings_manager: SettingsManager, settings: PersonSyncSettings) -> None:
    """
    Stores the person sync settings whole, creating the section on its first write

    The caller judges the settings first (``sync_settings_rules.find_sync_settings_problems``)

    Args:
        settings_manager (SettingsManager): The tenant's settings
        settings (PersonSyncSettings): The settings to store
    """
    settings_manager.write(PERSON_SYNC_SETTINGS_SECTION, settings_to_document(settings))


def switch_user_sync_off(settings: PersonSyncSettings) -> PersonSyncSettings:
    """
    Switches the user sync off - and the user group sync with it, whose members are the user sync's persons

    The targets stay chosen, so switching the sync on again needs no new choice

    Args:
        settings (PersonSyncSettings): The current settings

    Returns:
        PersonSyncSettings: The settings with both syncs off
    """
    return replace(settings, users=replace(settings.users, active=False), groups=replace(settings.groups, active=False))


def drop_type_override(settings_manager: SettingsManager, ledger: WriteLedger, user_id: int) -> bool:
    """
    Removes a deleted user's Type override from the stored settings - kept, it would name a missing user and refuse
    every later settings write, and keep its Type a target

    Reads the stored settings fresh, so several users deleted in one request each lose their own. Recorded in the
    ledger before the write, so an undo puts the stored settings back

    Args:
        settings_manager (SettingsManager): The tenant's settings
        ledger (WriteLedger): Records the write
        user_id (int): The deleted user

    Returns:
        bool: True when an override was removed
    """
    stored: PersonSyncSettings = read_sync_settings(settings_manager)

    if user_id not in stored.users.type_overrides:
        return False

    remaining: dict[int, int] = {
        override_user: type_id for override_user, type_id in stored.users.type_overrides.items()
        if override_user != user_id
    }
    ledger.compensated(
        SettingsManager.COLLECTION, f"type override of user {user_id} removed",
        lambda: write_sync_settings(settings_manager, stored),
        lambda: read_sync_settings(settings_manager) == stored,
    )
    write_sync_settings(settings_manager, replace(stored, users=replace(stored.users, type_overrides=remaining)))

    return True
