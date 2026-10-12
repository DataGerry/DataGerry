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
Database update 20261012: report every stored reference to a CmdbUserGroup that does not exist

Since this version nothing new can point at a missing group: a user write, the auth settings write and a type ACL
write refuse an unknown group, and a group delete is refused while the LDAP settings name the group or a type ACL
grants only it. What was stored before is only reported, never repaired - each repair is an administrator's choice:

  - a user in a missing group authenticates and is refused every right; moving it into group 2 could hand it rights
    it never had. Logged by public_id; its next save is refused until an existing group is picked
  - an LDAP default group or mapping row naming a missing group provisions directory users into it - the provider
    now skips such a group and refuses to provision without one. Logged by value; the settings' next save is refused
  - a type ACL entry for a missing group grants nobody and is inert - logged. A type whose ACTIVATED list grants no
    existing group at all is LOCKED: no API call can read, edit or delete it or its objects. Logged as an error; it
    can only be repaired in the database

Writes nothing, so a re-run reports the same
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals and the rule of this migration are frozen: it must keep meaning what it meant when it shipped
GROUP_COLLECTION: str = 'management.groups'
USER_COLLECTION: str = 'management.users'
TYPE_COLLECTION: str = 'framework.types'
SETTINGS_COLLECTION: str = 'settings.conf'
PUBLIC_ID_FIELD: str = 'public_id'
GROUP_ID_FIELD: str = 'group_id'
USER_NAME_FIELD: str = 'user_name'
NAME_FIELD: str = 'name'
ACL_FIELD: str = 'acl'
ACL_ACTIVATED: str = 'activated'
ACL_GROUPS: str = 'groups'
ACL_INCLUDES: str = 'includes'
SETTINGS_ID_FIELD: str = '_id'
AUTH_SETTINGS_ID: str = 'auth'
PROVIDERS: str = 'providers'
CLASS_NAME: str = 'class_name'
CONFIG: str = 'config'
LDAP_PROVIDER_CLASS_NAME: str = 'LdapAuthenticationProvider'
DEFAULT_GROUP: str = 'default_group'
LDAP_GROUPS: str = 'groups'
LDAP_DEFAULT_GROUP_ID: int = 2
MAPPING: str = 'mapping'
MAPPING_GROUP_ID: str = 'group_id'
MAPPING_GROUP_DN: str = 'group_dn'


def acl_includes(acl: Any) -> dict[str, Any]:
    """
    Answers the group key -> permissions mapping of a stored ``acl`` block

    Args:
        acl (Any): The stored block

    Returns:
        dict[str, Any]: The mapping; empty when any level of it is missing or not a document
    """
    groups: Any = acl.get(ACL_GROUPS) if isinstance(acl, dict) else None
    includes: Any = groups.get(ACL_INCLUDES) if isinstance(groups, dict) else None

    return includes if isinstance(includes, dict) else {}


def unknown_acl_keys(acl: Any, existing: set[int]) -> list[str]:
    """
    Answers the ``includes`` keys of a stored ``acl`` block that name no existing group

    Args:
        acl (Any): The stored block
        existing (set[int]): Every existing group's public_id

    Returns:
        list[str]: The keys, sorted - a key that is no number counts as unknown
    """
    return sorted(key for key in acl_includes(acl) if not (str(key).isdigit() and int(key) in existing))


def is_locked(acl: Any, existing: set[int]) -> bool:
    """
    Answers whether an activated ``acl`` block grants no existing group anything

    Args:
        acl (Any): The stored block
        existing (set[int]): Every existing group's public_id

    Returns:
        bool: True when the block is activated and every group it grants something is missing
    """
    if not isinstance(acl, dict) or acl.get(ACL_ACTIVATED) is not True:
        return False

    return not any(
        str(key).isdigit() and int(key) in existing and isinstance(permissions, list) and permissions
        for key, permissions in acl_includes(acl).items()
    )


def ldap_group_values(auth_settings: Any) -> list[tuple[Any, str | None]]:
    """
    Answers every group value the LDAP provider entries of a stored auth section name

    Args:
        auth_settings (Any): The stored ``auth`` settings document

    Returns:
        list[tuple[Any, str | None]]: (value, group_dn) pairs - the default group with no DN, then each mapping row
    """
    providers: Any = auth_settings.get(PROVIDERS) if isinstance(auth_settings, dict) else None
    values: list[tuple[Any, str | None]] = []

    for entry in providers if isinstance(providers, list) else []:
        if not isinstance(entry, dict) or entry.get(CLASS_NAME) != LDAP_PROVIDER_CLASS_NAME:
            continue

        config: Any = entry.get(CONFIG) if isinstance(entry.get(CONFIG), dict) else {}
        values.append((config.get(DEFAULT_GROUP) or LDAP_DEFAULT_GROUP_ID, None))
        groups: Any = config.get(LDAP_GROUPS)
        mapping: Any = groups.get(MAPPING) if isinstance(groups, dict) else None

        for row in mapping if isinstance(mapping, list) else []:
            if isinstance(row, dict):
                values.append((row.get(MAPPING_GROUP_ID), str(row.get(MAPPING_GROUP_DN) or '')))

    return values


def names_existing_group(value: Any, existing: set[int]) -> bool:
    """
    Answers whether a stored group value names an existing group, read the way the LDAP provider reads it

    Args:
        value (Any): The stored value
        existing (set[int]): Every existing group's public_id

    Returns:
        bool: True for an int (or a string of digits) that an existing group carries
    """
    if isinstance(value, bool):
        return False

    if isinstance(value, str) and value.isdigit():
        value = int(value)

    return isinstance(value, int) and value in existing


class Update20261012(BaseDatabaseUpdate):
    """
    Reports the stored users, LDAP settings and type ACLs that name a CmdbUserGroup that does not exist

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261012


    def description(self) -> str:
        return "Reports stored references to user groups that do not exist (writes nothing)"


    def start_update(self) -> None:
        """
        Reads the existing groups, reports each kind of reference to a missing one, then bumps the version

        Raises:
            UpdaterException: If a read failed
        """
        try:
            existing: set[int] = {
                document[PUBLIC_ID_FIELD]
                for document in self._read(GROUP_COLLECTION, {}, {PUBLIC_ID_FIELD: 1})
            }

            self.report_users(existing)
            self.report_ldap_settings(existing)
            self.report_type_acls(existing)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _read(self, collection: str, criteria: dict[str, Any], projection: dict[str, int]) -> list[dict[str, Any]]:
        """
        Reads one collection projected

        Args:
            collection (str): The collection
            criteria (dict[str, Any]): The filter
            projection (dict[str, int]): The fields to read

        Returns:
            list[dict[str, Any]]: The documents
        """
        return list(self.dbm.find(collection=collection, db_name=self.db_name, filter=criteria,
                                  projection={**projection, '_id': 0}))


    def report_users(self, existing: set[int]) -> None:
        """
        Logs every user whose group does not exist

        Args:
            existing (set[int]): Every existing group's public_id
        """
        criteria: dict[str, Any] = {GROUP_ID_FIELD: {'$nin': sorted(existing)}}

        for user in self._read(USER_COLLECTION, criteria, {PUBLIC_ID_FIELD: 1, USER_NAME_FIELD: 1, GROUP_ID_FIELD: 1}):
            LOGGER.warning("[Update20261012] '%s' user %s (%r) is in the missing UserGroup %r - it holds no right "
                           "until an administrator picks an existing group", self.db_name, user.get(PUBLIC_ID_FIELD),
                           user.get(USER_NAME_FIELD), user.get(GROUP_ID_FIELD))


    def report_ldap_settings(self, existing: set[int]) -> None:
        """
        Logs every LDAP default group or mapping row naming a group that does not exist

        Args:
            existing (set[int]): Every existing group's public_id
        """
        sections: list[dict[str, Any]] = self._read(SETTINGS_COLLECTION, {SETTINGS_ID_FIELD: AUTH_SETTINGS_ID},
                                                    {PROVIDERS: 1})

        for section in sections:
            for value, group_dn in ldap_group_values(section):
                if not names_existing_group(value, existing):
                    LOGGER.warning("[Update20261012] '%s' the LDAP %s names the missing UserGroup %r",
                                   self.db_name, f"mapping of {group_dn!r}" if group_dn is not None
                                   else "default group", value)


    def report_type_acls(self, existing: set[int]) -> None:
        """
        Logs every type ACL entry naming a missing group, and every type locked by its ACL as an error

        Args:
            existing (set[int]): Every existing group's public_id
        """
        criteria: dict[str, Any] = {f'{ACL_FIELD}.{ACL_GROUPS}.{ACL_INCLUDES}': {'$type': 'object'}}

        for document in self._read(TYPE_COLLECTION, criteria, {PUBLIC_ID_FIELD: 1, NAME_FIELD: 1, ACL_FIELD: 1}):
            acl: Any = document.get(ACL_FIELD)
            unknown: list[str] = unknown_acl_keys(acl, existing)

            if is_locked(acl, existing):
                LOGGER.error("[Update20261012] '%s' type %s (%r) is LOCKED: its activated access control list grants "
                             "no existing UserGroup, so no API call can read, edit or delete it - repair its acl in "
                             "the database", self.db_name, document.get(PUBLIC_ID_FIELD), document.get(NAME_FIELD))
            elif unknown:
                LOGGER.warning("[Update20261012] '%s' type %s (%r) has access control entries for the missing "
                               "UserGroup(s) %s - they grant nobody", self.db_name, document.get(PUBLIC_ID_FIELD),
                               document.get(NAME_FIELD), unknown)
