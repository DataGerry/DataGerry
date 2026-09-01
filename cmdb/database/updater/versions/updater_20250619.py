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
Database update 20250619: backfill CI-Explorer fields on objects and types

The CI Explorer reads a per-object tooltip and a per-type label + color. Installations that predate
those properties carry documents without them, so this update fills in the neutral defaults:

* every CmdbObject missing ``ci_explorer_tooltip`` gets ``None``;
* every CmdbType missing ``ci_explorer_label`` gets ``None``;
* every CmdbType missing ``ci_explorer_color`` gets its own random color, so the types are
  distinguishable in the Explorer instead of all rendering colorless.

Only documents that lack a property are touched: a value already stored - including a color a user
picked - is never overwritten. All three properties are optional and nullable in the object / type
schemas and every reader resolves them with ``.get``, so this migration is a convenience, not a
correctness prerequisite.

**Re-run safety.** The version is persisted as the last statement, so a failure re-enters this
migration on the next boot. Each backfill is filtered on ``{'$exists': False}``, which makes the
tooltip and label steps fully idempotent: a repeated run writes nothing. The color step is idempotent
per document too (a stored color is never touched), but the colors it assigns are **random**, so a run
that dies halfway leaves the already-coloured types alone and gives the remaining ones *different*
colors than the interrupted run would have. That is accepted: any color is as good as any other, and
the alternative (deriving the color from the type) was deliberately not chosen.
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from cmdb.utils import random_hex_color

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Document keys this migration backfills
OBJECT_TOOLTIP_FIELD: str = 'ci_explorer_tooltip'
TYPE_LABEL_FIELD: str = 'ci_explorer_label'
TYPE_COLOR_FIELD: str = 'ci_explorer_color'

# Identity key of every CmdbDAO document
PUBLIC_ID_FIELD: str = 'public_id'
MONGO_ID_FIELD: str = '_id'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20250619 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20250619(BaseDatabaseUpdate):
    """
    Backfills CI-Explorer fields: 'ci_explorer_tooltip' on objects, plus 'ci_explorer_color' and
    'ci_explorer_label' on types

    One-way, re-runnable and non-destructive (a stored value is never overwritten); the assigned type
    colors are random - see the module docstring

    Extends: BaseDatabaseUpdate
    """

    def creation_date(self) -> int:
        return 20250619


    def description(self) -> str:
        return ("Adds 'ci_explorer_tooltip' to all CmdbObjects and 'ci_explorer_color' / "
                "'ci_explorer_label' to all CmdbTypes which don't have them")


    def start_update(self) -> None:
        """
        Adds the missing CI-Explorer fields to every object and type that does not already have them

        Runs the object backfill, then the two type backfills, and persists the updater version last -
        a failure anywhere before that leaves the version untouched and repeats the whole migration on
        the next boot, which is safe (see the module docstring)

        Raises:
            UpdaterException: If any step of the migration fails (every error is wrapped)
        """
        try:
            self.backfill_object_tooltips()
            self.backfill_type_labels()
            self.backfill_type_colors()

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err

# ------------------------------------------------- BACKFILL METHODS ------------------------------------------------- #

    def backfill_object_tooltips(self) -> None:
        """
        Sets ``ci_explorer_tooltip`` to None on every CmdbObject that does not carry it

        One server-side bulk update filtered on the missing property: no document is loaded into the
        process, and objects that already have a tooltip are not matched at all
        """
        result = self.dbm.update_many_raw(
            collection=CmdbObject.COLLECTION,
            db_name=self.db_name,
            filter_query={OBJECT_TOOLTIP_FIELD: {'$exists': False}},
            update={'$set': {OBJECT_TOOLTIP_FIELD: None}},
        )

        LOGGER.info("Backfilled '%s' on %s CmdbObject(s)", OBJECT_TOOLTIP_FIELD, result.modified_count)


    def backfill_type_labels(self) -> None:
        """
        Sets ``ci_explorer_label`` to None on every CmdbType that does not carry it

        The same single bulk update as the object tooltip: the value is the same for every type, so no
        per-document work is needed
        """
        result = self.dbm.update_many_raw(
            collection=CmdbType.COLLECTION,
            db_name=self.db_name,
            filter_query={TYPE_LABEL_FIELD: {'$exists': False}},
            update={'$set': {TYPE_LABEL_FIELD: None}},
        )

        LOGGER.info("Backfilled '%s' on %s CmdbType(s)", TYPE_LABEL_FIELD, result.modified_count)


    def backfill_type_colors(self) -> None:
        """
        Gives every CmdbType that does not carry ``ci_explorer_color`` its own random color

        Each type needs a *different* value, so this cannot be a single update. It stays one round trip
        per batch instead of one per type: only the public_ids of the types missing the color are read
        (filtered and projected server-side), and the writes are handed to one batched bulk_write. A
        type document without a public_id cannot be addressed and is skipped with a warning - that
        should never happen, since public_id is the identity key of every CmdbDAO document
        """
        types_without_color: list[dict[str, Any]] = self.dbm.find_all(
            CmdbType.COLLECTION,
            self.db_name,
            filter={TYPE_COLOR_FIELD: {'$exists': False}},
            projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0},
        )

        operations: list[UpdateOne] = []

        for a_type in types_without_color:
            type_public_id: Any = a_type.get(PUBLIC_ID_FIELD)

            if not type_public_id:
                LOGGER.warning(
                    "Skipped a %s document without a '%s' while backfilling '%s'",
                    CmdbType.COLLECTION, PUBLIC_ID_FIELD, TYPE_COLOR_FIELD,
                )
                continue

            operations.append(UpdateOne(
                {PUBLIC_ID_FIELD: type_public_id},
                {'$set': {TYPE_COLOR_FIELD: random_hex_color()}},
            ))

        if not operations:
            LOGGER.info("Backfilled '%s' on 0 CmdbType(s)", TYPE_COLOR_FIELD)
            return

        self.dbm.bulk_write(CmdbType.COLLECTION, self.db_name, operations)

        LOGGER.info("Backfilled '%s' on %s CmdbType(s)", TYPE_COLOR_FIELD, len(operations))
