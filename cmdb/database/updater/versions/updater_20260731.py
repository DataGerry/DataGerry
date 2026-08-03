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
Database update 20260731: backfill 'mds_mode' and 'predefined' on every CmdbReport missing them
"""
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.mds_mode_enum import MdsMode

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

# The two report keys the validation schema treats as optional (both default in the model) but which a
# stored document is expected to carry: 'mds_mode' postdates the reporting feature, so every report
# created before the multi-data-section modes exists without it, and a report inserted outside the REST
# routes may lack 'predefined' the same way
MDS_MODE_KEY: str = 'mds_mode'
PREDEFINED_KEY: str = 'predefined'

DEFAULT_MDS_MODE: str = MdsMode.ROWS.value
DEFAULT_PREDEFINED: bool = False
# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260731 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260731(BaseDatabaseUpdate):
    """
    Normalises CmdbReport documents that predate the 'mds_mode' / 'predefined' keys
    """
    def creation_date(self) -> int:
        return 20260731


    def description(self) -> str:
        return "Backfills 'mds_mode' and 'predefined' on CmdbReports missing them"


    def start_update(self) -> None:
        """
        Sets the default 'mds_mode' / 'predefined' on every report document that lacks the key

        Two server-side ``$set`` updates, each filtered on ``{'$exists': False}``, so no document is
        loaded into the process and a report that already carries the key is not matched - which also
        makes the migration re-run safe: a second run (or a re-run after a crash between the two
        updates) matches nothing for the keys already written and completes the remainder. Reading a
        report tolerates both keys being absent, so this is data hygiene rather than a repair: it keeps
        the stored documents in line with what every writer produces

        Raises:
            UpdaterException: If one of the updates fails
        """
        try:
            self.dbm.update_many_raw(
                collection=CmdbReport.COLLECTION,
                db_name=self.db_name,
                filter_query={MDS_MODE_KEY: {'$exists': False}},
                update={'$set': {MDS_MODE_KEY: DEFAULT_MDS_MODE}},
            )

            self.dbm.update_many_raw(
                collection=CmdbReport.COLLECTION,
                db_name=self.db_name,
                filter_query={PREDEFINED_KEY: {'$exists': False}},
                update={'$set': {PREDEFINED_KEY: DEFAULT_PREDEFINED}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
