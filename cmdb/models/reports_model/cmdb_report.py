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
This module contains the implementation of CmdbReport, a saved query over a CmdbType in DataGerry

A report (collection ``framework.reports``) pairs a CmdbType with the field names to output
(``selected_fields``) and a filter (``conditions``): a nested tree whose nodes are either groups
combining child rules with a logical operator or leaf rules naming a field, an operator and a value -
see ReportConditionKey / ReportConditionLogic / ReportQueryOperator in this package. The compiled
MongoDB form of that tree is stored alongside it as ``report_query`` and is what a report run
executes; the REST layer owns building it, so the two are only consistent as long as every writer
rebuilds the query after touching the conditions.

Besides the usual serialization this module provides the condition-tree surgery that runs when a
CmdbType loses a field: ``clear_rules_of_field`` strips every rule referencing that field and
``CmdbReport.remove_field_occurrences`` applies it to a report together with its selected fields.
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.reports_model.report_constants import ReportConditionKey

from cmdb.class_schema.reports_model.cmdb_report_schema import get_cmdb_report_schema

from cmdb.errors.models.cmdb_report import (
    CmdbReportInitError,
    CmdbReportInitFromDataError,
    CmdbReportToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #


def clear_rules_of_field(conditions: dict[str, Any] | None, field_name: str) -> dict[str, Any] | None:
    """
    Recursively strips every rule referencing a field from a report's condition tree

    Walks the tree depth-first and rebuilds it without the leaf rules naming ``field_name`` and
    without the groups those rules leave empty. A group is only kept when it still has at least one
    rule, so a tree that loses all of its rules collapses to None - which the query builder then
    compiles into a type-only query, i.e. the report widens to every object of its CmdbType. That is
    the accepted behaviour: no conditions means no filtering

    The returned tree is a new structure at group level, but the surviving leaf rules are the same
    dict objects as in the input - callers must not mutate them in place. Malformed nodes are treated
    conservatively: a group without a logical operator keeps its (missing) operator rather than having
    one invented, and a leaf without a field name is not the searched field and is therefore kept

    Args:
        conditions (dict[str, Any] | None): The condition tree (or subtree) to strip
        field_name (str): Name of the field whose rules should be removed

    Returns:
        dict[str, Any] | None: The stripped tree, or None when nothing is left of it
    """
    if not conditions:
        return None

    stripped: dict[str, Any] = {ReportConditionKey.CONDITION: conditions.get(ReportConditionKey.CONDITION)}
    kept_rules: list[dict[str, Any]] = []

    for a_rule in conditions.get(ReportConditionKey.RULES, []):
        if ReportConditionKey.CONDITION in a_rule:
            nested: dict[str, Any] | None = clear_rules_of_field(a_rule, field_name)

            if nested:
                kept_rules.append(nested)
        elif a_rule.get(ReportConditionKey.FIELD) != field_name:
            kept_rules.append(a_rule)

    if not kept_rules:
        return None

    stripped[ReportConditionKey.RULES] = kept_rules

    return stripped

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbReport - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbReport(CmdbDAO):
    """
    Implementation of a CmdbReport in DataGerry

    Holds the report's identity, its CmdbType, the selected output fields, the condition tree, the
    compiled report query and the MDS render mode, plus the (de)serialization between that state and
    the stored document

    Extends: CmdbDAO
    """

    COLLECTION = 'framework.reports'
    MODEL = 'Report'
    DEFAULT_VERSION: str = '1.0.0'

    # Both keys back an existence / count check that must not scan the collection: 'report_category_id'
    # serves the delete guard of a CmdbReportCategory (a category may not be deleted while a report
    # references it) and the category list's per-category counts, 'type_id' serves the report count of a
    # CmdbType, which the type-delete flow asks for
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('report_category_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'report_category_id',
            'unique': False,
        },
        {
            'keys': [('type_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'type_id',
            'unique': False,
        },
    ]

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

    SCHEMA: dict[str, Any] = get_cmdb_report_schema()


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
        mds_mode: MdsMode | str = MdsMode.ROWS,
        **kwargs: Any
    ) -> None:
        """
        Initialize a new CmdbReport instance

        Args:
            report_category_id (int): public_id of the CmdbReportCategory the report belongs to
            name (str): Name of the report
            type_id (int): public_id of the CmdbType the report runs against
            selected_fields (list[str]): Names of the type fields the report outputs
            conditions (dict[str, Any] | None): The report's condition tree, or None for no filter
            report_query (dict[str, Any] | None): The compiled MongoDB form of the conditions, built
                by the REST layer and rebuilt whenever the conditions change
            predefined (bool): True when the report is provided by DataGerry. Defaults to False
            mds_mode (MdsMode | str): Multi-data-section render mode. The write routes store an
                MdsMode member; a stored document holds its string value. Defaults to MdsMode.ROWS
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
            self.mds_mode: MdsMode | str = mds_mode

            super().__init__(**kwargs)
        except Exception as err:
            raise CmdbReportInitError(str(err)) from err


    def remove_field_occurrences(self, field_name: str) -> None:
        """
        Removes every occurrence of a field from the report's selected fields and conditions

        Both attributes are replaced rather than mutated: the selected fields become a new list
        without the name (all of its occurrences, should the list hold duplicates) and the conditions
        are rebuilt by clear_rules_of_field. The stored document a report was loaded from therefore
        stays untouched, and the caller is responsible for rebuilding ``report_query`` from the new
        conditions before persisting

        Args:
            field_name (str): The name of the field to remove
        """
        self.selected_fields = [a_field for a_field in self.selected_fields if a_field != field_name]
        self.conditions = clear_rules_of_field(self.conditions, field_name)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbReport":
        """
        Creates a CmdbReport instance from a stored document

        The four keys the validation schema marks as required are read strictly - a document without
        them is broken and should surface as an error. 'mds_mode' and 'predefined' are optional in the
        schema and default in the constructor, so they are read leniently: a report written before the
        MDS mode existed carries neither, and a strict read would fail the whole report list (every
        row of an iteration is hydrated through this method) instead of that single document

        Args:
            data (dict[str, Any]): A dictionary representing report data

        Raises:
            CmdbReportInitFromDataError: If the instance could not be created from the given data

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
                mds_mode = data.get('mds_mode', MdsMode.ROWS),
                predefined = data.get('predefined', False),
            )
        except Exception as err:
            raise CmdbReportInitFromDataError(str(err)) from err

    @classmethod
    def to_json(cls, instance: "CmdbReport") -> dict[str, Any]:
        """
        Converts a CmdbReport instance into a dictionary suitable for JSON serialization

        Args:
            instance (CmdbReport): The report instance to serialize

        Raises:
            CmdbReportToJsonError: If the CmdbReport could not be converted to a json compatible dict

        Returns:
            dict[str, Any]: A dictionary representation of the CmdbReport instance
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
