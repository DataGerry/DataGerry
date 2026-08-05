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
This module contains the implementation of the ReportCategoriesManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory

from cmdb.errors.manager.report_categories_manager import REPORT_CATEGORIES_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ReportCategoriesManager - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class ReportCategoriesManager(GenericManager):
    """
    The ReportCategoriesManager manages the interaction between CmdbReportCategories and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ReportCategoriesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            ReportCategoriesManagerInitError: If the ReportCategoriesManager could not be initialised
        """
        super().__init__(dbm, CmdbReportCategory, REPORT_CATEGORIES_MANAGER_ERRORS, database)
