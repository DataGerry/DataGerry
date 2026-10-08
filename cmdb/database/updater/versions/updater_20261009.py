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
Database update 20261009: give every stored CmdbWebhook an owner

Since this version a webhook only receives the writes of objects its owner may read, and its owner is the user who
last saved it (``owner_id``, set by the server). A webhook stored before carries no owner and would receive nothing.
This update makes it the administrators': its owner becomes the lowest-numbered ACTIVE user of the fixed admin
group, so a stored webhook keeps delivering whatever the admin group may read - every type, except one whose activated
ACL leaves the admin group out - until someone saves it again and becomes its owner. A database without any active
admin-group user leaves its webhooks ownerless (and logs it).

Idempotent by construction: only a webhook without the key is selected, and every one written gets it
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
WEBHOOK_COLLECTION: str = 'framework.webhooks'
USER_COLLECTION: str = 'management.users'
OWNER_FIELD: str = 'owner_id'
GROUP_FIELD: str = 'group_id'
ACTIVE_FIELD: str = 'active'
PUBLIC_ID_FIELD: str = 'public_id'
ADMIN_GROUP_ID: int = 1

# The user this update makes the owner: the first active member of the admin group
ADMIN_CRITERIA: dict[str, Any] = {GROUP_FIELD: ADMIN_GROUP_ID, ACTIVE_FIELD: True}

# The webhooks this update visits: those without the key
OWNERLESS_CRITERIA: dict[str, Any] = {OWNER_FIELD: {'$exists': False}}


class Update20261009(BaseDatabaseUpdate):
    """
    Makes the first active admin-group user the owner of every stored CmdbWebhook without one

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261009


    def description(self) -> str:
        return "Gives every stored webhook an owner: the first active user of the admin group"


    def start_update(self) -> None:
        """
        Reads the first active admin-group user, stamps it on every ownerless webhook, then bumps the version

        Raises:
            UpdaterException: If the read or the write failed
        """
        try:
            admins: list[dict[str, Any]] = list(self.dbm.find(
                collection=USER_COLLECTION,
                db_name=self.db_name,
                filter=ADMIN_CRITERIA,
                projection={PUBLIC_ID_FIELD: 1, '_id': 0},
                sort=[(PUBLIC_ID_FIELD, 1)],
                limit=1,
            ))

            if admins:
                self.dbm.update_many_raw(
                    collection=WEBHOOK_COLLECTION,
                    db_name=self.db_name,
                    filter_query=OWNERLESS_CRITERIA,
                    update={'$set': {OWNER_FIELD: admins[0][PUBLIC_ID_FIELD]}},
                )
            else:
                LOGGER.warning("[Update20261009] No active admin-group user in '%s' - stored webhooks stay without "
                               "an owner and receive nothing until saved again", self.db_name)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
