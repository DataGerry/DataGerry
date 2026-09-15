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
Database update 20260417: give every CmdbType and CmdbObject a 'special_type' key

The marker names the SpecialType flavour a CmdbType carries (RACK, SUBNET, VLAN, ...) and is copied
onto that type's CmdbObjects; a document with no flavour carries the empty marker. This migration only
ensures the KEY EXISTS - it never assigns a flavour, which happens when a special type is created.

**It writes ``''`` and that is deliberate, not a bug to correct here.** The model and both Cerberus
schemas have since settled on ``None`` as the no-flavour value (``special_type: str | None = None``,
``'nullable': True``), so a database that ran this migration carries ``''`` where anything written
since carries ``None``. The two are equivalent to every reader today - each lookup targets a specific
member and ``SpecialType.is_ipam_type`` validates before comparing - but they are still two spellings
of one fact, and ``updater_20260908`` is what converges them. This module keeps writing ``''``
because a shipped migration must stay a faithful record of what it did: databases past this version
are never revisited, so changing it here would only add a third population.

Idempotent by construction: the ``$exists: False`` filter matches nothing on a second run, which is
also what makes a partial failure safe - the version is bumped only after both collections are done,
so an interrupted run simply repeats
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The no-flavour marker this migration writes. Kept as its own constant so updater_20260908, which
# normalises it away, can name exactly what it is looking for
LEGACY_EMPTY_SPECIAL_TYPE: str = ''

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260417 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260417(BaseDatabaseUpdate):
    """
    Backfills an empty 'special_type' marker onto every CmdbType and CmdbObject that lacks it
    """
    def creation_date(self) -> int:
        return 20260417


    def description(self) -> str:
        return ("Gives every Type and Object a 'special_type' key, with the empty marker for the ones "
                "that carry no SpecialType flavour")


    def start_update(self) -> None:
        """
        Sets 'special_type' to the empty marker on every type and object that lacks the key

        Raises:
            UpdaterException: If either collection could not be updated
        """
        try:
            type_result = self.types_manager.update_many(
                criteria={TypeSchemaKey.SPECIAL_TYPE.value: {"$exists": False}},
                update={TypeSchemaKey.SPECIAL_TYPE.value: LEGACY_EMPTY_SPECIAL_TYPE},
            )

            object_result = self.objects_manager.update_many(
                criteria={CmdbObjectKey.SPECIAL_TYPE.value: {"$exists": False}},
                update={CmdbObjectKey.SPECIAL_TYPE.value: LEGACY_EMPTY_SPECIAL_TYPE},
            )

            LOGGER.info(
                "[Update20260417] Backfilled 'special_type' on %s CmdbTypes and %s CmdbObjects",
                type_result.modified_count, object_result.modified_count,
            )

            # Only after BOTH collections are done: an interrupted run leaves the version untouched and
            # repeats, which the $exists filter makes harmless
            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
