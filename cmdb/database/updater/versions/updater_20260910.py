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
Database update 20260910: the object relations' timestamps become real dates

The sibling of ``updater_20260907``, which did this for the two ISMS collections. The same defect was
live in ``framework.objectRelations``, and for a narrower reason: the create route stamped
``creation_time`` itself - so that key was always a real date - but left ``last_edit_time`` to the
request body, where the frontend's ``{'$date': <millis>}`` wrapper passed validation (the schema typed
the key ``dict``) and was stored as a **sub-document**.

Two consequences, both of them invisible until someone looked: MongoDB cannot sort or range-filter a
sub-document as a date, and the relation-tab route accepts an arbitrary ``?sort=`` field, so sorting a
tab by ``last_edit_time`` ordered by BSON type instead of by time; and the two timestamps of one
collection had two different types, so any code reading them had to handle both.

Since 2026-09-08 the create route clears ``last_edit_time`` and both keys are declared in
``CmdbObjectRelation.DATE_FIELDS``, so every write path normalises them. This migration converts what
is already stored.

``creation_time`` is converted too. Nothing is known to have written a wrapper there - the route
stamped a datetime from the beginning - but a document restored from an old dump or written by an
integration would be indistinguishable, and converting a key that already holds a date is free: the
filter does not match it.

The conversion itself is imported from ``updater_20260907`` rather than copied. Its pipeline is the
subtle part - the inner key starts with a ``$`` and can only be reached with ``$getField`` +
``$literal``, and the two ``onError`` / ``onNull`` arms are what keep an unreadable value from being
nulled - and one implementation of that is worth more than two frozen copies. The literals this module
owns (its collection and its keys) are local and frozen, as a migration's literals must be.

Idempotent: selection is by BSON type, so a converted field is a date and no longer matches. The
version is bumped once both keys are done, so an interrupted run repeats harmlessly
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.updater.versions.updater_20260907 import convert_wrapped_dates

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Frozen at migration time - see the module docstring
OBJECT_RELATION_COLLECTION: str = 'framework.objectRelations'
OBJECT_RELATION_DATE_FIELDS: tuple[str, ...] = ('creation_time', 'last_edit_time')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260910 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260910(BaseDatabaseUpdate):
    """
    Converts the stored CmdbObjectRelation timestamps from '$date' wrappers into real BSON dates
    """
    def creation_date(self) -> int:
        return 20260910


    def description(self) -> str:
        return ("Converts the CmdbObjectRelation 'creation_time' and 'last_edit_time' values from "
                "'$date' wrapper sub-documents into real BSON dates, so they can be sorted and filtered")


    def start_update(self) -> None:
        """
        Converts both timestamps of the object-relation collection, then bumps the updater version

        Raises:
            UpdaterException: If any of the conversions fails
        """
        try:
            for field in OBJECT_RELATION_DATE_FIELDS:
                converted: int = convert_wrapped_dates(
                    self.dbm,
                    self.db_name,
                    OBJECT_RELATION_COLLECTION,
                    field,
                )

                if converted:
                    LOGGER.info(
                        "[Update20260910] Converted %s '%s' value(s) in %s into real dates",
                        converted, field, OBJECT_RELATION_COLLECTION,
                    )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
