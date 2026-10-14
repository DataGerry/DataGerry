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
Implementation of CmdbReportCategory, the group a CmdbReport belongs to

A category is three keys - ``ReportCategoryKey``: its public_id, its name and whether DataGerry provides it
(``predefined``, the seeded 'General' category). It declares them as its ``KEYS``, so the shared CmdbDAO from_data /
to_json read and write exactly those; ``normalize_document`` keeps the one lenient read the model always had - a
stored category without ``predefined`` is a user-created one
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.reports_model.report_constants import ReportCategoryKey

from cmdb.class_schema.reports_model.cmdb_report_category_schema import get_cmdb_report_category_schema

from cmdb.errors.models.cmdb_report_category import (
    CmdbReportCategoryInitError,
    CmdbReportCategoryInitFromDataError,
    CmdbReportCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbReportCategory - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbReportCategory(CmdbDAO):
    """
    Implementation of a CmdbReportCategory in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.reportCategories'
    # What its own from_data / to_json raise - declared so a manager can tell a document that no longer
    # fits the model from a programming error (GenericManager._model_errors)
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbReportCategoryInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbReportCategoryToJsonError
    DEFAULT_VERSION: str = '1.0.0'
    REQUIRED_INIT_KEYS: list[str] = [ReportCategoryKey.NAME.value, ReportCategoryKey.PREDEFINED.value]
    KEYS = ReportCategoryKey

    SCHEMA: dict[str, Any] = get_cmdb_report_category_schema()

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(self, *, name: str, predefined: bool = False, **kwargs: Any) -> None:
        """
        Initialises a CmdbReportCategory

        Args:
            name (str): name of the CmdbReportCategory
            predefined (bool, optional): If True then the CmdbReportCategory is provided by DataGerry. Defaults to False

        Raises:
            CmdbReportCategoryInitError: If the CmdbReportCategory could not be initialised
        """
        try:
            self.name = name
            self.predefined = predefined

            super().__init__(**kwargs)
        except Exception as err:
            raise CmdbReportCategoryInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Reads a stored category without ``predefined`` as a user-created one, before the shared from_data

        Args:
            data (dict[str, Any]): The document, edited in place
        """
        data.setdefault(ReportCategoryKey.PREDEFINED.value, False)
