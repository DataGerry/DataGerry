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
This module contains the implementation of CmdbReportCategory, which is representing
a category of a CmdbReport in DataGarry
"""
from cmdb.models.cmdb_dao import CmdbDAO

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
    MODEL = 'Report_Category'
    DEFAULT_VERSION: str = '1.0.0'
    REQUIRED_INIT_KEYS = ['name', 'predefined']

    SCHEMA: dict = get_cmdb_report_category_schema()

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(self, name: str, predefined: bool = False, **kwargs):
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
    def from_data(cls, data: dict) -> "CmdbReportCategory":
        """
        Initialises a CmdbReportCategory from a dict

        Args:
            data (dict): Data with which the CmdbReportCategory should be initialised

        Raises:
            CmdbReportCategoryInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbReportCategory: CmdbReportCategory with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                predefined = data.get('predefined', False),
            )
        except Exception as err:
            raise CmdbReportCategoryInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbReportCategory") -> dict:
        """
        Converts a CmdbReportCategory into a json compatible dict

        Args:
            instance (CmdbReportCategory): The CmdbReportCategory which should be converted

        Raises:
            CmdbReportCategoryToJsonError: If the CmdbReportCategory could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbReportCategory values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'predefined': instance.predefined,
            }
        except Exception as err:
            raise CmdbReportCategoryToJsonError(err) from err
