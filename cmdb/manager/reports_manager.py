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
from typing import Any

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager, MongoDBQueryBuilder
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.report_constants import ReportQueryKey
from cmdb.models.type_model import CmdbType

from cmdb.errors.manager.reports_manager import REPORTS_MANAGER_ERRORS, ReportsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ReportsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ReportsManager(GenericManager):
    """
    The ReportsManager manages the interaction between CmdbReports and the database

    A GenericManager specialisation bound to the CmdbReport model and the report error map: it
    inherits the generic CRUD surface (insert / get / update / delete / iterate / count) on the
    CmdbReport collection and adds one domain operation - stripping fields that no longer exist out
    of the reports that select or filter on them

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


    def strip_removed_fields_from_reports(
        self,
        reports_for_type: list[dict[str, Any]],
        removed_field_names: set[str],
        type_instance: CmdbType,
    ) -> int:
        """
        Removes field names that no longer exist from a CmdbType's reports and rebuilds their queries

        A report references its columns and filter operands by field name, so a field dropped from
        the type leaves the report selecting and filtering on something that cannot match. For every
        report of the type this drops each removed name from 'selected_fields' and from the condition
        tree, rebuilds the persisted 'report_query' from what is left, and writes all reports back in
        a single bulk operation

        Lives here rather than in the REST layer because two non-route callers need it: the global
        section-template removal (which rewrites types directly, bypassing the type-update route's
        realignment) and the database updaters. A no-op when nothing was removed or the type has no
        reports, so it is safe to call unconditionally and safe to run twice

        Args:
            reports_for_type (list[dict[str, Any]]): The stored reports belonging to the type
            removed_field_names (set[str]): Field names that no longer exist on the type
            type_instance (CmdbType): The CmdbType the reports belong to (drives the query rebuild)

        Raises:
            ReportsManagerUpdateError: If the bulk write of the cleaned reports fails

        Returns:
            int: Number of reports written
        """
        if not removed_field_names or not reports_for_type:
            return 0

        try:
            report_ops: list[UpdateOne] = []

            for a_report in reports_for_type:
                tmp_report: CmdbReport = CmdbReport.from_data(a_report)

                for field_name in removed_field_names:
                    tmp_report.remove_field_occurrences(field_name)

                tmp_report.report_query = {
                    ReportQueryKey.DATA: str(MongoDBQueryBuilder(tmp_report.conditions, type_instance).build())
                }
                report_ops.append(
                    UpdateOne({CmdbObjectKey.PUBLIC_ID.value: tmp_report.public_id}, {'$set': tmp_report.__dict__})
                )

            # No emptiness guard needed: the early return above rules out an empty report list, and
            # every report yields exactly one operation
            self.bulk_write(report_ops)

            return len(report_ops)
        except Exception as err:
            LOGGER.error("[strip_removed_fields_from_reports] Error: %s. Type: %s", err, type(err))
            raise ReportsManagerUpdateError(str(err)) from err
