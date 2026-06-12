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
Translates a CmdbReport's condition rule tree into a MongoDB query

A report stores its filter as a nested condition tree (see ReportConditionKey): each node is either
a group combining its children with a logical operator ('and' / 'or', see ReportConditionLogic) or a
leaf rule pairing a field name with a comparison operator (ReportQueryOperator) and a value.
MongoDBQueryBuilder walks that tree depth-first and produces the equivalent MongoDB query document,
scoped to the report's CmdbType via a single top-level ``type_id`` constraint.

The report type's fields are classified once on construction so that each leaf rule can:
  * coerce its value to the matching Python type - ``datetime`` for date fields, ``int`` for number
    and reference fields (per element when the operator takes a list, e.g. ``in`` / ``not in``);
  * target the right document path - the flat ``fields`` array, or the nested
    ``multi_data_sections.values.data`` array for multi-data-section fields.

The produced query uses plain ``str`` keys / values (the field-key enums are reduced to their string
values) so the document survives the ``repr`` round-trip the report routes rely on to persist and
re-evaluate it.
"""
import re
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from cmdb.models.type_model import CmdbType, FieldType
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.reports_model.report_constants import (
    ReportConditionKey,
    ReportConditionLogic,
    ReportQueryOperator,
)

from cmdb.errors.mongo_query_builder import (
    MongoQueryBuilderInitError,
    MongoQueryBuilderInvalidOperatorError,
    MongoQueryBuilderBuildRuleError,
    MongoQueryBuilderBuildRulesetError,
    MongoQueryBuilderBuildError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Date leaf-rule values are stored / sent in ISO date form
DATE_FORMAT: str = '%Y-%m-%d'

# Document paths a leaf rule may target (plain strings, so the query survives the repr round-trip)
FIELDS_PATH: str = CmdbObjectKey.FIELDS.value
MDS_VALUES_PATH: str = (
    f"{CmdbObjectKey.MULTI_DATA_SECTIONS.value}"
    f".{CmdbObjectMdsKey.VALUES.value}"
    f".{CmdbObjectMdsRowKey.DATA.value}"
)
TYPE_ID_KEY: str = CmdbObjectKey.TYPE_ID.value
FIELD_NAME_KEY: str = CmdbObjectFieldKey.NAME.value
FIELD_VALUE_KEY: str = CmdbObjectFieldKey.VALUE.value

# -------------------------------------------------------------------------------------------------------------------- #
#                                              MongoDBQueryBuilder - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class MongoDBQueryBuilder:
    """
    Builds a MongoDB query document from a report's condition rule tree
    """
    # Logical group operators -> their MongoDB combiner
    __CONDITION_COMBINERS: dict[str, str] = {
        ReportConditionLogic.AND: '$and',
        ReportConditionLogic.OR: '$or',
    }

    # Comparison operators that map directly to a single MongoDB operator wrapping the value
    __DIRECT_OPERATORS: dict[str, str] = {
        ReportQueryOperator.EQ: '$eq',
        ReportQueryOperator.NE: '$ne',
        ReportQueryOperator.LTE: '$lte',
        ReportQueryOperator.GTE: '$gte',
        ReportQueryOperator.LT: '$lt',
        ReportQueryOperator.GT: '$gt',
        ReportQueryOperator.IN: '$in',
        ReportQueryOperator.NOT_IN: '$nin',
    }

    # Operators whose value is a list and therefore coerced element-by-element
    __MULTI_VALUE_OPERATORS: tuple[str, ...] = (ReportQueryOperator.IN, ReportQueryOperator.NOT_IN)

    def __init__(self, query_data: dict[str, Any] | None, report_type: CmdbType) -> None:
        """
        Initializes a MongoDBQueryBuilder instance

        Classifies the report type's fields by FieldType so leaf rules can later coerce their value
        and pick the right document path

        Args:
            query_data (dict[str, Any] | None): The report's conditions ('condition' + 'rules'),
                                                or None for a type-only query
            report_type (CmdbType): The CmdbType the report runs against

        Raises:
            MongoQueryBuilderInitError: If initialization fails
        """
        try:
            self.condition: str | None = None
            self.rules: list[dict[str, Any]] | None = None

            if query_data:
                self.condition = query_data.get(ReportConditionKey.CONDITION)
                self.rules = query_data.get(ReportConditionKey.RULES)

            self.report_type: CmdbType = report_type

            self.number_fields: list[str] = self.report_type.get_all_fields_of_type(FieldType.NUMBER)
            self.date_fields: list[str] = self.report_type.get_all_fields_of_type(FieldType.DATE)
            self.ref_fields: list[str] = self.report_type.get_all_fields_of_type(FieldType.REFERENCE)
            self.ref_section_fields: list[str] = self.report_type.get_all_fields_of_type(FieldType.REF_SECTION)
            # get_all_mds_fields returns MDS field *names* (render_meta sections store field names),
            # so this is a list[str] and the `field_name in self.mds_fields` check below works
            self.mds_fields: list[str] = self.report_type.get_all_mds_fields()
        except Exception as err:
            LOGGER.error("[__init__] Initialization failed. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderInitError(f"Failed to initialize MongoDBQueryBuilder: {err}") from err


    def build(self) -> dict[str, Any]:
        """
        Builds the MongoDB query from the report's condition and rules

        The query is always scoped to the report's CmdbType. When there are rules, the built ruleset
        is AND-ed with that ``type_id`` constraint exactly once at the top level

        Returns:
            dict[str, Any]: The constructed MongoDB query

        Raises:
            MongoQueryBuilderBuildError: If query building fails
        """
        try:
            type_filter: dict[str, Any] = {TYPE_ID_KEY: self.report_type.public_id}

            if not (self.condition and self.rules):
                return type_filter

            return {'$and': [self.__build_ruleset(self.condition, self.rules), type_filter]}
        except Exception as err:
            LOGGER.error("[build] Query building failed. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildError(f"Failed to build MongoDB query: {err}") from err


    def __build_ruleset(self, condition: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Recursively constructs the MongoDB combiner for one condition group

        Args:
            condition (str): Logical group operator ('and' / 'or') combining the rules
            rules (list[dict[str, Any]]): The group's child rules - each a nested group (carrying its
                                          own 'condition') or a leaf rule (carrying 'field')

        Returns:
            dict[str, Any]: ``{'$and': [...]}`` or ``{'$or': [...]}`` for the group (no type scoping;
                            the type constraint is added once by build())

        Raises:
            MongoQueryBuilderBuildRulesetError: If the condition is unknown or ruleset construction
                                                fails
        """
        try:
            children: list[dict[str, Any]] = []

            for rule in rules:
                if ReportConditionKey.CONDITION in rule:
                    children.append(self.__build_ruleset(rule[ReportConditionKey.CONDITION],
                                                         rule[ReportConditionKey.RULES]))
                else:
                    children.append(self.__build_rule(rule[ReportConditionKey.FIELD],
                                                      rule[ReportConditionKey.OPERATOR],
                                                      rule.get(ReportConditionKey.VALUE)))

            return {self.__CONDITION_COMBINERS[condition]: children}
        except KeyError as err:
            LOGGER.error("[__build_ruleset] Unknown condition operator: %s", err)
            raise MongoQueryBuilderBuildRulesetError(f"Unknown condition operator: {condition}") from err
        except MongoQueryBuilderInvalidOperatorError:
            raise
        except Exception as err:
            LOGGER.error("[__build_ruleset] Failed to build ruleset. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRulesetError(f"Error building MongoDB ruleset: {err}") from err


    def __build_rule(
        self,
        field_name: str,
        operator: str,
        value: int | str | list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Builds the MongoDB fragment for a single leaf rule

        Resolves the document path (flat ``fields`` or the nested MDS values path), coerces the value
        to the field's Python type and delegates the $elemMatch assembly to the rule helpers

        Args:
            field_name (str): The name of the field to filter by
            operator (str): The comparison operator (see ReportQueryOperator)
            value (int | str | list[str] | None): The value(s) to compare against

        Returns:
            dict[str, Any]: A MongoDB query fragment for the rule

        Raises:
            MongoQueryBuilderInvalidOperatorError: If the operator is not supported
            MongoQueryBuilderBuildRuleError: If any other error occurs during rule creation
        """
        try:
            target_field: str = MDS_VALUES_PATH if field_name in self.mds_fields else FIELDS_PATH
            target_value = self._coerce_value(field_name, operator, value)

            return self._create_rule(target_field, operator, field_name, target_value)
        except MongoQueryBuilderInvalidOperatorError:
            raise
        except Exception as err:
            LOGGER.error("[__build_rule] Exception: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def _coerce_value(
        self,
        field_name: str,
        operator: str,
        value: int | str | list[Any] | None,
    ) -> int | str | list[Any] | datetime | None:
        """
        Coerces a leaf rule's value to the Python type matching the field

        Date fields are parsed to ``datetime``, number / reference fields to ``int``; all other
        fields keep their value unchanged. For list-valued operators (``in`` / ``not in``) every list
        element is coerced individually. An empty / falsy value is returned untouched

        Args:
            field_name (str): The name of the field being filtered
            operator (str): The comparison operator (decides single- vs list-valued coercion)
            value (int | str | list[Any] | None): The raw rule value

        Returns:
            int | str | list[Any] | datetime | None: The coerced value
        """
        if not value:
            return value

        if field_name in self.date_fields:
            converter = self._parse_date
        elif (field_name in self.ref_fields
              or field_name in self.ref_section_fields
              or field_name in self.number_fields):
            converter = int
        else:
            return value

        if operator in self.__MULTI_VALUE_OPERATORS and isinstance(value, list):
            return [converter(item) for item in value]

        return converter(value)


    @staticmethod
    def _parse_date(value: str) -> datetime:
        """
        Parses an ISO date string (YYYY-MM-DD) into a datetime

        Args:
            value (str): The date string to parse

        Returns:
            datetime: The parsed datetime
        """
        return datetime.strptime(value, DATE_FORMAT)


    def _create_rule(
        self,
        target_field: str,
        operator: str,
        field_name: str,
        value: int | str | list[int] | list[str] | datetime | None = None,
    ) -> dict[str, Any]:
        """
        Transforms a leaf rule into a MongoDB compatible query part

        Args:
            target_field (str): Document path to match against (FIELDS_PATH or MDS_VALUES_PATH)
            operator (str): The comparison operator of the rule
            field_name (str): The name of the field
            value (int | str | list[int] | list[str] | datetime | None): The (already coerced) value

        Returns:
            dict[str, Any]: The rule as a MongoDB compatible query part

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator was provided
            MongoQueryBuilderBuildRuleError: If assembling the rule fails
        """
        try:
            return {target_field: self._get_operator_fragment(operator, field_name, value)}
        except MongoQueryBuilderInvalidOperatorError:
            raise
        except Exception as err:
            LOGGER.error("[_create_rule] Exception: %s. Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err


    def _get_operator_fragment(
        self,
        operator: str,
        field_name: str,
        value: int | str | list[int] | list[str] | datetime | None = None,
    ) -> dict[str, Any]:
        """
        Builds the $elemMatch fragment matching a field entry by name and value

        Args:
            operator (str): The comparison operator of the condition
            field_name (str): The name of the field of the condition
            value (int | str | list[int] | list[str] | datetime | None): The value of the condition

        Returns:
            dict[str, Any]: The $elemMatch fragment for the condition

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator was provided
            MongoQueryBuilderBuildRuleError: If assembling the fragment fails
        """
        try:
            return {
                '$elemMatch': {
                    FIELD_NAME_KEY: field_name,
                    FIELD_VALUE_KEY: self._get_value_fragment(operator, value),
                }
            }
        except MongoQueryBuilderInvalidOperatorError:
            raise
        except Exception as err:
            LOGGER.error("[_get_operator_fragment] Unexpected error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRuleError(str(err)) from err


    def _get_value_fragment(
        self,
        operator: str,
        value: int | str | list[int] | list[str] | datetime | None = None,
    ) -> dict[str, Any]:
        """
        Builds the value-comparison fragment for a single operator

        Only the fragment for the requested operator is constructed. ``contains`` and ``like`` match
        the value as a regular expression with the user input regex-escaped (so it is matched
        literally, never interpreted as a pattern); ``like`` additionally matches case-insensitively

        Args:
            operator (str): The comparison operator (see ReportQueryOperator)
            value (int | str | list[int] | list[str] | datetime | None): The value of the condition

        Returns:
            dict[str, Any]: The value part of the condition

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator is provided
        """
        if operator in self.__DIRECT_OPERATORS:
            return {self.__DIRECT_OPERATORS[operator]: value}

        if operator == ReportQueryOperator.CONTAINS:
            return {'$regex': re.escape(str(value))}

        if operator == ReportQueryOperator.LIKE:
            return {'$regex': re.escape(str(value)), '$options': 'i'}

        if operator == ReportQueryOperator.IS_NULL:
            return {'$in': [None, ""]}

        if operator == ReportQueryOperator.IS_NOT_NULL:
            return {'$nin': [None, ""]}

        raise MongoQueryBuilderInvalidOperatorError(operator)
