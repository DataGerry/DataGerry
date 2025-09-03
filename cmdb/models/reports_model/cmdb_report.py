# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module contains the implementation of CmdbReport, which is representing a report in Datagarry
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.reports_model.mds_mode_enum import MdsMode

from cmdb.errors.models.cmdb_report import (
    CmdbReportInitError,
    CmdbReportInitFromDataError,
    CmdbReportToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbReport - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbReport(CmdbDAO):
    """
    Represents a report object.
    Manages data relevant to reports including metadata, fields selection, query conditions,
    and methods to manipulate and serialize report data.
    """

    COLLECTION = 'framework.reports'
    MODEL = 'Report'
    DEFAULT_VERSION: str = '1.0.0'

    REQUIRED_INIT_KEYS: list[str] = [
        'report_category_id',
        'name',
        'type_id',
        'selected_fields',
        'conditions',
        'report_query',
        'predefined',
        'mds_mode',
    ]

    SCHEMA: dict[str, Any] = {
        'public_id': {
            'type': 'integer'
        },
        'report_category_id': {
            'type': 'integer',
            'required': True,
        },
        'name': {
            'type': 'string',
            'required': True,
        },
        'type_id': {
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'selected_fields': {
            'type': 'list',
            'required': True,
        },
        'conditions': {
            'type': 'dict',
        },
        'report_query': {
            'type': 'dict',
        },
        'predefined': {
            'type': 'boolean',
            'default': False
        },
        'mds_mode': {
            'type': 'string',
        },
    }


    #pylint: disable=R0913, R0917
    def __init__(
        self,
        report_category_id: int,
        name: str,
        type_id: int,
        selected_fields: list[str],
        conditions: dict[str, Any] | None,
        report_query: dict[str, Any] | None,
        predefined: bool = False,
        mds_mode: str = MdsMode.ROWS,
        **kwargs: Any
    ) -> None:
        """
        Initialize a new CmdbReport instance

        Args:
            report_category_id (int): The ID of the report category
            name (str): Name of the report
            type_id (int): The report type identifier
            selected_fields (list): Fields selected for the report
            conditions (dict): Conditions applied to the report
            report_query (dict): Query used to generate the report
            predefined (bool): Whether the report is predefined. Default is False
            mds_mode (str): MDS mode, typically 'ROWS' or another display mode
            **kwargs: Additional keyword arguments for the parent class

        Raises:
            CmdbReportInitError: If the CmdbReport could not be initialised
        """
        try:
            self.report_category_id: int = report_category_id
            self.name: str = name
            self.type_id: int = type_id
            self.selected_fields: list[str] = selected_fields
            self.conditions: dict[str, Any] | None = conditions
            self.report_query: dict[str, Any] | None = report_query
            self.predefined: bool = predefined
            self.mds_mode: str = mds_mode

            super().__init__(**kwargs)
        except Exception as err:
            raise CmdbReportInitError(str(err)) from err


    def get_selected_fields(self) -> list[str]:
        """
        Returns the list of selected fields for the report

        Returns:
            list: A list of selected field names
        """
        return self.selected_fields


    def remove_field_occurences(self, field_name: str) -> None:
        """
        Remove all occurrences of a field from both selected fields and conditions

        Args:
            field_name (str): The name of the field to remove
        """
        # Remove field from selected fields
        if field_name in self.selected_fields:
            self.selected_fields.remove(field_name)

        # Remove field from conditions
        self.conditions = self.clear_rules_of_field(self.conditions, field_name)


    def clear_rules_of_field(self, conditions: dict[str, Any] | None, field_name: str) -> dict[str, Any] | None:
        """
        Recursively clears rules associated with a specific field from the conditions dictionary

        Args:
            conditions (dict): The conditions structure from which the field rules should be removed
            field_name (str): The name of the field to remove

        Returns:
            dict | None: The updated conditions dictionary or None if all relevant rules were removed
        """
        if not conditions:
            return None

        new_conditions: dict[str, Any] = {'condition': conditions['condition']}
        new_rules: list[dict[str, Any]] = []

        for a_rule in conditions.get('rules', []):
            if "condition" in a_rule:
                result: dict[str, Any] | None = self.clear_rules_of_field(a_rule, field_name)

                if result:
                    new_rules.append(result)
            else:
                if a_rule['field'] == field_name:
                    pass
                else:
                    new_rules.append(a_rule)

        if len(new_rules) > 0:
            new_conditions['rules'] = new_rules
            return new_conditions

        return None

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbReport":
        """
        Creates a CmdbReport instance from a dictionary of data

        Args:
            data (dict): A dictionary representing report data

        Returns:
            CmdbReport: An instance of CmdbReport initialized with the provided data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                report_category_id = data['report_category_id'],
                name = data['name'],
                type_id = data['type_id'],
                selected_fields = data['selected_fields'],
                conditions = data.get('conditions'),
                report_query = data.get('report_query'),
                mds_mode = data['mds_mode'],
                predefined = data['predefined'],
            )
        except Exception as err:
            raise CmdbReportInitFromDataError(str(err)) from err

    @classmethod
    def to_json(cls, instance: "CmdbReport") -> dict[str, Any]:
        """
        Converts a CmdbReport instance into a dictionary suitable for JSON serialization

        Args:
            instance (CmdbReport): The report instance to serialize

        Returns:
            dict: A dictionary representation of the CmdbReport instance
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'report_category_id': instance.report_category_id,
                'name': instance.name,
                'type_id': instance.type_id,
                'selected_fields': instance.selected_fields,
                'conditions': instance.conditions,
                'report_query': instance.report_query,
                'predefined': instance.predefined,
                'mds_mode': instance.mds_mode,
            }
        except Exception as err:
            raise CmdbReportToJsonError(str(err)) from err
