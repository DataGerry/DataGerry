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
The module builds a MongoDB query for a dict of conditions
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from cmdb.models.type_model import CmdbType

from cmdb.errors.mongo_query_builder import (
    MongoQueryBuilderInitError,
    MongoQueryBuilderInvalidOperatorError,
    MongoQueryBuilderBuildRuleError,
    MongoQueryBuilderBuildRulesetError,
    MongoQueryBuilderBuildError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              MongoDBQueryBuilder - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class MongoDBQueryBuilder:
    """
    The MongoDBQueryBuilder generates a MongoDB query from a dict of rules
    """
    def __init__(self, query_data: dict[str, Any] | None, report_type: CmdbType) -> None:
        """
        Initializes a MongoQueryBuilder instance

        Args:
            query_data (dict): Data containing the query condition and rules
            report_type (CmdbType): The CMDB type object containing field definitions

        Raises:
            MongoQueryBuilderInitError: If initialization fails
        """
        try:
            self.condition: str | None = None
            self.rules: list[dict[str, Any]] | None = None

            if query_data:
                self.condition = query_data.get("condition")
                self.rules = query_data.get("rules")

            self.report_type: CmdbType = report_type

            self.number_fields: list[str] = self.report_type.get_all_fields_of_type("number")
            self.date_fields: list[str] = self.report_type.get_all_fields_of_type("date")
            self.ref_fields: list[str] = self.report_type.get_all_fields_of_type("ref")
            self.ref_section_fields: list[str] = self.report_type.get_all_fields_of_type("ref-section-field")
            self.mds_fields: list[dict[str, Any]] = self.report_type.get_all_mds_fields()
        except Exception as err:
            LOGGER.error("[__init__] Initialization failed. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderInitError(f"Failed to initialize MongoQueryBuilder: {err}") from err


    def build(self) -> dict[str, Any]:
        """
        Builds the MongoDB query using the defined condition and rules

        Returns:
            dict: The constructed MongoDB query

        Raises:
            MongoQueryBuilderBuildError: If query building fails
        """
        try:
            return self.__build_ruleset(self.condition, self.rules)
        except Exception as err:
            LOGGER.error("[build] Query building failed. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildError(f"Failed to build MongoDB query: {err}") from err


    def __build_ruleset(self, condition: str | None, rules: list[dict[str, Any]] | None) -> dict[str, Any]:
        """
        Recursively constructs a MongoDB query ruleset based on the provided condition and rules

        Args:
            condition (str): Logical condition ('and' or 'or') for combining rules
            rules (list[dict]): List of rules or nested rule sets

        Returns:
            dict: A MongoDB query representation of the ruleset

        Raises:
            MongoQueryBuilderBuildRulesetError: If ruleset construction fails
        """
        try:
            if self.condition and self.rules:
                children = []

                for rule in rules:
                    if "condition" in rule:
                        children.append(self.__build_ruleset(rule["condition"], rule["rules"]))
                    else:
                        children.append(self.__build_rule(rule["field"], rule["operator"], rule.get("value")))

                possible_conditions = {
                    "and": {'$and': [{'$and': children}, {"type_id": self.report_type.public_id}]},
                    "or": {'$and': [{'$or': children}, {"type_id": self.report_type.public_id}]},
                }

                return possible_conditions[condition]

            return {"type_id": self.report_type.public_id}
        except Exception as err:
            LOGGER.error("[__build_ruleset] Failed to build ruleset. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRulesetError(f"Error building MongoDB ruleset: {err}") from err


    def __build_rule(
        self,
        field_name: str,
        operator: str,
        value: int | str | list[str] | None = None
    ) -> dict[str, Any]:
        """
        Builds a query rule for MongoDB based on the provided field name, operator, and value

        Args:
            field_name (str): The name of the field to filter by
            operator (str): The comparison operator (e.g., "$eq", "$gt", "$in")
            value (int | str | list[str], optional): The value(s) to compare against

        Raises:
            MongoQueryBuilderInvalidOperatorError: If the provided operator is invalid
            MongoQueryBuilderBuildRuleError: If any other error occurs during rule creation

        Returns:
            dict: A MongoDB query rule
        """
        try:
            target_field = "fields"
            target_value: int | str | list[str] | datetime | None = value

            if field_name in self.date_fields and value:
                target_value = datetime.strptime(value, '%Y-%m-%d')

            if (field_name in self.ref_fields
                or field_name in self.ref_section_fields
                or field_name in self.number_fields
               ) and value:
                target_value = int(value)

            if field_name in self.mds_fields:
                target_field = "multi_data_sections.values.data"

            return self.create_rule(target_field, operator, field_name, target_value)
        except MongoQueryBuilderInvalidOperatorError as err:
            raise MongoQueryBuilderInvalidOperatorError(f"Invalid operator: {operator}") from err
        except Exception as err:
            LOGGER.error("[__build_rule] Exception: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def create_rule(
        self,
        target_field: str,
        operator: str,
        field_name: str,
        value: int | str | list[int] | list[str] | datetime | None = None
    ) -> dict[str, Any]:
        """
        Transforms a rule to a MongoDB compatible query part
        
        Args:
            target_field (str): defines where to search for the value (fields or MDS)
            operator (str): operator of the rule
            field_name (str): name of field
            value (int | str | list[int] | list[str], optional): value of the rule

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator was provided

        Returns:
            dict: rule as MongoDB compatible query part
        """
        try:
            return {
                target_field: self.get_operator_fragment(operator, field_name, value)
            }
        except MongoQueryBuilderInvalidOperatorError as err:
            raise MongoQueryBuilderInvalidOperatorError(operator) from err
        except Exception as err:
            LOGGER.error("[create_rule] Exception: %s. Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err

    def get_operator_fragment(
        self,
        operator: str,
        field_name: str,
        value: int | str | list[int] | list[str] | datetime | None = None
    ) -> dict[str, Any]:
        """
        Creates the operator part of a condition for a MongoDB query

        Args:
            operator (str): operator of the condition like '<, =, !='
            field_name (str): field name of the condition
            value (int | str | list[int] | list[str], optional): value of the condition

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator was provided

        Returns:
            dict: operator part of the condition
        """
        try:
            return {
                "$elemMatch": {
                    "name": field_name,
                    "value": self.get_value_fragment(operator, value)
                }
            }
        except MongoQueryBuilderInvalidOperatorError as err:
            raise MongoQueryBuilderInvalidOperatorError(f"Invalid value for operator '{operator}'") from err
        except Exception as err:
            LOGGER.error("[get_operator_fragment] Unexpected error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err


    def get_value_fragment(
        self,
        operator: str,
        value: int | str | list[int] | list[str] | datetime | None = None
    ) -> dict[str, Any] | str:
        """
        Creates the value part of a condition for a MongoDB query

        Args:
            operator (str): operator of the condition like '<, =, !='
            value (int | str | list[int] | list[str], optional): value of the condition

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator is provided

        Returns:
            dict | str | None: Value part of a condition
        """

        allowed_operators: dict[str, Any] = {
            "=": {"$eq": value},
            "!=": {"$ne": value},
            "<=": {"$lte": value},
            ">=": {"$gte": value},
            "<": {"$lt": value},
            ">": {"$gt": value},
            "in": {"$in": value},
            "not in": {"$nin": value},
            "contains": {"$regex": value},
            "like": "/"+str(value)+"/",
            "is null": {"$in": [None, ""]},
            "is not null": {"$nin": [None, ""]},
        }

        if operator in allowed_operators:
            return allowed_operators[operator]

        raise MongoQueryBuilderInvalidOperatorError(operator)
