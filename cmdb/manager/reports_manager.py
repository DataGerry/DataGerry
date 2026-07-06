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
This module contains the implementation of the ReportsManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.reports_model.cmdb_report import CmdbReport

from cmdb.errors.manager.reports_manager import REPORTS_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ReportsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ReportsManager(GenericManager):
    """
    The ReportsManager manages the interaction between CmdbReports and the database

    A thin GenericManager specialisation bound to the CmdbReport model and the report error map:
    it inherits the generic CRUD surface (insert / get / update / delete / iterate / count) on the
    CmdbReport collection and adds no behaviour of its own. The report's condition tree is translated
    into its persisted query by MongoDBQueryBuilder in the REST layer, not here

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None):
        """
        Initializes the ReportsManager

        Args:
            dbm (MongoDatabaseManager): Database interface used for the report collection
            database (str | None): Name of the database to operate on (cloud mode); defaults to the
                                   connection's configured database when None
        """
        super().__init__(dbm, CmdbReport, REPORTS_MANAGER_ERRORS, database)
