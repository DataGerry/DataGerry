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
Database update 20260908: one spelling for "this Type carries no SpecialType"

``special_type`` had two no-flavour spellings in the wild:

* ``''`` - written by ``updater_20260417``, which backfilled the key onto every existing CmdbType and
  CmdbObject
* ``None`` - what the model and both Cerberus schemas settled on afterwards
  (``special_type: str | None = None``, ``'required': False, 'nullable': True``), so it is what every
  document written through ``CmdbType.to_json`` / ``CmdbObject.to_json`` has carried since

Nothing reads them differently *today*: every lookup targets a specific member
(``get_one_by({SPECIAL_TYPE: 'RACK'})``), the comparisons are ``special_type == SpecialType.X``, and
``SpecialType.is_ipam_type`` validates before comparing, so both fall through as "not a special type".
The problem is what that costs the next change: a single ``{'special_type': {'$ne': None}}`` - the
obvious way to ask "which types are special?" - would silently count every pre-migration document as
one. This migration removes that trap by converging on the model's value.

Also covers documents that never got the key at all, which is what ``updater_20260417`` was reaching
for: after this runs, every CmdbType and CmdbObject has the key, and it is either a SpecialType member
or null.

Idempotent: the filter matches only the two states being normalised, so a second run matches nothing.
The version is bumped once both collections are done, so an interrupted run repeats harmlessly
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.updater.versions.updater_20260417 import LEGACY_EMPTY_SPECIAL_TYPE

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The value the model, the schemas and every write path since updater_20260417 use for "no flavour"
NO_SPECIAL_TYPE: None = None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260908 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260908(BaseDatabaseUpdate):
    """
    Normalises the empty 'special_type' marker and the missing key onto the model's None
    """
    def creation_date(self) -> int:
        return 20260908


    def description(self) -> str:
        return ("Normalises the 'special_type' marker of Types and Objects: the empty string written "
                "by an earlier update, and a missing key, both become null")


    def start_update(self) -> None:
        """
        Rewrites the empty marker and the absent key as null, on both collections

        Raises:
            UpdaterException: If either collection could not be updated
        """
        try:
            type_result = self.types_manager.update_many(
                criteria=self._legacy_marker_criteria(TypeSchemaKey.SPECIAL_TYPE.value),
                update={TypeSchemaKey.SPECIAL_TYPE.value: NO_SPECIAL_TYPE},
            )

            object_result = self.objects_manager.update_many(
                criteria=self._legacy_marker_criteria(CmdbObjectKey.SPECIAL_TYPE.value),
                update={CmdbObjectKey.SPECIAL_TYPE.value: NO_SPECIAL_TYPE},
            )

            LOGGER.info(
                "[Update20260908] Normalised 'special_type' on %s CmdbTypes and %s CmdbObjects",
                type_result.modified_count, object_result.modified_count,
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    @staticmethod
    def _legacy_marker_criteria(special_type_key: str) -> dict[str, Any]:
        """
        Builds the filter selecting the documents whose marker needs normalising

        Deliberately narrow: it matches the empty marker and the absent key, and **nothing else**. A
        document already carrying null is left alone (so a re-run modifies nothing), and one carrying a
        real SpecialType member is never touched - this migration must not be able to un-assign a
        flavour.

        Args:
            special_type_key (str): The collection's 'special_type' key

        Returns:
            dict[str, Any]: The filter for one collection
        """
        return {
            "$or": [
                {special_type_key: LEGACY_EMPTY_SPECIAL_TYPE},
                {special_type_key: {"$exists": False}},
            ]
        }
