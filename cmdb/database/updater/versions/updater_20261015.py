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
Database update 20261015: stores the auth providers' on/off flags spelled as "true" / "false" as real booleans

Since this version a provider config's ``active`` flag and the LDAP group-mapping flag (``groups.active``) must be
booleans: a config holding anything else cannot be built, and the read then falls back to the provider's defaults -
for LDAP that is "switched off". Before, a stored string was read by its truthiness, so ``"true"`` worked as on and
``"false"`` was read as on as well.

Each flag stored as exactly ``"true"`` or ``"false"`` becomes that boolean. ``"true"`` keeps working; ``"false"``
now means what it says, so an LDAP provider or group mapping that was running against its stored setting stops.
Any other non-boolean value is left as it is and logged: its meaning is not unambiguous, and the read falls back to
the provider's defaults until an administrator saves the settings again.

Idempotent by construction: only the two strings are rewritten, and every rewrite stores a boolean, so a second run
changes nothing
"""
from copy import deepcopy
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
SETTINGS_COLLECTION: str = 'settings.conf'
SETTINGS_ID_FIELD: str = '_id'
AUTH_SETTINGS_ID: str = 'auth'
PROVIDERS: str = 'providers'
CLASS_NAME: str = 'class_name'
CONFIG: str = 'config'
ACTIVE: str = 'active'
LDAP_GROUPS: str = 'groups'
GROUPS_ACTIVE_FLAG: str = f'{LDAP_GROUPS}.{ACTIVE}'
FLAG_SPELLINGS: dict[str, bool] = {'true': True, 'false': False}


def flag_holders(config: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """
    Answers the documents of one provider config that hold an on/off flag under `active`, with the flag's name in a
    report

    Args:
        config (dict[str, Any]): A stored provider config

    Returns:
        list[tuple[dict[str, Any], str]]: The config itself, and its `groups` when that is a document
    """
    holders: list[tuple[dict[str, Any], str]] = [(config, ACTIVE)]
    groups: Any = config.get(LDAP_GROUPS)

    if isinstance(groups, dict):
        holders.append((groups, GROUPS_ACTIVE_FLAG))

    return holders


def normalised_providers(providers: Any) -> tuple[list[Any], list[str], list[str]]:
    """
    Rewrites the flags spelled "true" / "false" in a stored provider list, and names the ones left alone

    Args:
        providers (Any): The stored `providers` list

    Returns:
        tuple[list[Any], list[str], list[str]]: The rewritten list (a copy); one line per rewritten flag; one line per
            flag holding another non-boolean value
    """
    rewritten: list[Any] = deepcopy(providers) if isinstance(providers, list) else []
    changed: list[str] = []
    left_alone: list[str] = []

    for entry in rewritten:
        config: Any = entry.get(CONFIG) if isinstance(entry, dict) else None

        if not isinstance(config, dict):
            continue

        for holder, flag in flag_holders(config):
            value: Any = holder.get(ACTIVE)

            if value is None or isinstance(value, bool):
                continue

            label: str = f'{entry.get(CLASS_NAME)} {flag}={value!r}'

            if isinstance(value, str) and value in FLAG_SPELLINGS:
                holder[ACTIVE] = FLAG_SPELLINGS[value]
                changed.append(label)
            else:
                left_alone.append(label)

    return rewritten, changed, left_alone

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261015 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261015(BaseDatabaseUpdate):
    """
    Stores the auth providers' flags spelled "true" / "false" as booleans

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261015


    def description(self) -> str:
        return "Stores the auth providers' 'active' flags spelled as \"true\" / \"false\" as booleans"


    def start_update(self) -> None:
        """
        Rewrites the stored flags, then bumps the version

        Raises:
            UpdaterException: If the read or the write failed
        """
        try:
            self.normalise_auth_flags()
            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def normalise_auth_flags(self) -> list[str]:
        """
        Reads the stored 'auth' section and writes its provider list back when a flag was rewritten

        The write is conditioned on the list that was read, so a section saved in between is left alone

        Returns:
            list[str]: One line per rewritten flag
        """
        section: dict[str, Any] | None = self.dbm.get_collection(SETTINGS_COLLECTION, self.db_name).find_one(
            {SETTINGS_ID_FIELD: AUTH_SETTINGS_ID},
        )

        if not section:
            return []

        rewritten, changed, left_alone = normalised_providers(section.get(PROVIDERS))

        for label in left_alone:
            LOGGER.warning("[Update20261015] The auth provider flag %s is no boolean - the provider is read with its "
                           "defaults until the auth settings are saved again", label)

        if changed:
            self.dbm.update(
                SETTINGS_COLLECTION,
                self.db_name,
                {SETTINGS_ID_FIELD: AUTH_SETTINGS_ID, PROVIDERS: section.get(PROVIDERS)},
                {PROVIDERS: rewritten},
            )
            LOGGER.info("[Update20261015] Stored the auth provider flag(s) as booleans: %s", ', '.join(changed))

        return changed
