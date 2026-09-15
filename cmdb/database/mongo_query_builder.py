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

Two semantics are worth knowing before changing anything here:

  * **Date rules are day-granular.** A date field stores a full timestamp while a rule carries only
    ``YYYY-MM-DD``, so comparing against the parsed midnight would silently drop everything that
    happened later that day (``<= 2026-08-06`` would exclude an object created at 14:30 on exactly
    that date). Every date comparison is therefore widened to the whole day - see
    ``_build_date_value_fragment``.
  * **"is null" also matches a missing entry.** A field added to a CmdbType after an object was
    created leaves that object with no entry for it at all, which an ``$elemMatch`` can never match.
    The IS_NULL rule is therefore an ``$or`` of "entry exists and is empty" and "no such entry".

The MongoDB operator names (``'$and'``, ``'$elemMatch'``, ...) are written as bare literals here, in
the same way ``manager/query_builder/builder.py`` does: they are the database's wire vocabulary. The
DataGerry document keys around them are NOT literals - they come from the field-key enums at the top
of this module. Note that this builder emits query OPERATORS nested inside ``$elemMatch`` rather than
pipeline stages, which is why it does not go through ``Builder``: that class supplies stage
constructors, not the operator vocabulary needed here.
"""
import re
from logging import Logger, getLogger
from typing import Any, Callable
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
    MongoDBQueryBuilderError,
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

# The values a field entry may hold and still count as "empty" for the null operators
EMPTY_VALUES: tuple[Any, ...] = (None, "")

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


def build_contains_fragment(value: Any) -> dict[str, Any]:
    """
    Builds the case-sensitive substring fragment for the `contains` operator

    The value is regex-escaped, so a term carrying regex metacharacters is matched literally instead
    of being interpreted as a pattern

    Args:
        value (Any): The raw rule value

    Returns:
        dict[str, Any]: A `$regex` fragment
    """
    return {'$regex': re.escape(str(value))}


def build_like_fragment(value: Any) -> dict[str, Any]:
    """
    Builds the case-insensitive substring fragment for the `like` operator

    Args:
        value (Any): The raw rule value

    Returns:
        dict[str, Any]: A case-insensitive `$regex` fragment
    """
    return {'$regex': re.escape(str(value)), '$options': 'i'}


def build_is_null_fragment(_value: Any = None) -> dict[str, Any]:
    """
    Builds the "entry exists but carries no value" fragment

    Only half of the `is null` rule: an object that has no entry for the field at all cannot be
    matched by an `$elemMatch`, so `_create_rule` ORs this with a "no such entry" fragment

    Args:
        _value (Any): Unused - the operator takes no value

    Returns:
        dict[str, Any]: An `$in` fragment over the empty values
    """
    return {'$in': list(EMPTY_VALUES)}


def build_is_not_null_fragment(_value: Any = None) -> dict[str, Any]:
    """
    Builds the "entry exists and carries a value" fragment

    Needs no missing-entry counterpart: an object without an entry for the field has no value, so
    excluding it is correct

    Args:
        _value (Any): Unused - the operator takes no value

    Returns:
        dict[str, Any]: A `$nin` fragment over the empty values
    """
    return {'$nin': list(EMPTY_VALUES)}

# -------------------------------------------------------------------------------------------------------------------- #
#                                              MongoDBQueryBuilder - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class MongoDBQueryBuilder:
    """
    Builds a MongoDB query document from a report's condition rule tree
    """
    # These lookups are keyed by the ReportQueryOperator / ReportConditionLogic members but are read
    # with the plain strings a stored report document carries. That works because both enums extend
    # BaseStrEnum, i.e. they ARE strings and hash like their value - do not replace the members with
    # anything that is not a str subclass

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

    # Comparison operators whose fragment is assembled rather than wrapping the value directly
    __VALUE_FRAGMENT_BUILDERS: dict[str, Callable[[Any], dict[str, Any]]] = {
        ReportQueryOperator.CONTAINS: build_contains_fragment,
        ReportQueryOperator.LIKE: build_like_fragment,
        ReportQueryOperator.IS_NULL: build_is_null_fragment,
        ReportQueryOperator.IS_NOT_NULL: build_is_not_null_fragment,
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
            MongoQueryBuilderInvalidOperatorError: If a leaf rule uses an unsupported operator
            MongoQueryBuilderBuildRulesetError: If a condition group is malformed
            MongoQueryBuilderBuildRuleError: If a leaf rule cannot be built (e.g. an unparsable date)
            MongoQueryBuilderBuildError: If query building fails for any other reason
        """
        try:
            type_filter: dict[str, Any] = {TYPE_ID_KEY: self.report_type.public_id}

            if not (self.condition and self.rules):
                return type_filter

            return {'$and': [self.__build_ruleset(self.condition, self.rules), type_filter]}
        except MongoDBQueryBuilderError:
            # Already a precise builder error - re-raised so the caller can tell an invalid operator
            # or a malformed rule (both caller-fixable, answered with a 400) from an internal failure
            raise
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
            MongoQueryBuilderBuildRulesetError: If the condition is unknown, a rule is missing a
                                                required key, or ruleset construction fails
        """
        combiner: str | None = self.__CONDITION_COMBINERS.get(condition)

        if combiner is None:
            LOGGER.error("[__build_ruleset] Unknown condition operator: %s", condition)
            raise MongoQueryBuilderBuildRulesetError(f"Unknown condition operator: {condition}")

        try:
            children: list[dict[str, Any]] = [self.__build_node(rule) for rule in rules]

            return {combiner: children}
        except MongoDBQueryBuilderError:
            raise
        except Exception as err:
            LOGGER.error("[__build_ruleset] Failed to build ruleset. Error: %s, Type: %s", err, type(err))
            raise MongoQueryBuilderBuildRulesetError(f"Error building MongoDB ruleset: {err}") from err


    def __build_node(self, rule: dict[str, Any]) -> dict[str, Any]:
        """
        Builds one child of a condition group - either a nested group or a leaf rule

        Separated from `__build_ruleset` so a missing key is reported against the node that actually
        lacks it: reading the leaf keys inside the group's own try block used to surface every
        KeyError as "Unknown condition operator", pointing at the wrong part of the tree

        Args:
            rule (dict[str, Any]): The node - a group carrying 'condition' + 'rules', or a leaf
                carrying 'field' + 'operator' (+ an optional 'value')

        Returns:
            dict[str, Any]: The MongoDB fragment for that node

        Raises:
            MongoQueryBuilderBuildRulesetError: If the node is missing a key its shape requires
        """
        if ReportConditionKey.CONDITION in rule:
            return self.__build_ruleset(rule[ReportConditionKey.CONDITION],
                                        self.__require_key(rule, ReportConditionKey.RULES))

        return self.__build_rule(self.__require_key(rule, ReportConditionKey.FIELD),
                                 self.__require_key(rule, ReportConditionKey.OPERATOR),
                                 rule.get(ReportConditionKey.VALUE))


    @staticmethod
    def __require_key(rule: dict[str, Any], key: ReportConditionKey) -> Any:
        """
        Reads a required key of a condition node, naming the node when it is absent

        The message interpolates ``key.value``, not the member: BaseStrEnum does not override
        ``__str__``, so an f-string over the member itself would report 'ReportConditionKey.FIELD'
        instead of the 'field' an operator is looking for in the stored document

        Args:
            rule (dict[str, Any]): The condition node
            key (ReportConditionKey): The key the node's shape requires

        Returns:
            Any: The value stored under the key

        Raises:
            MongoQueryBuilderBuildRulesetError: If the key is missing
        """
        if key not in rule:
            LOGGER.error("[__require_key] Condition rule is missing the '%s' key: %s", key.value, rule)
            raise MongoQueryBuilderBuildRulesetError(
                f"Condition rule is missing the '{key.value}' key: {rule}"
            )

        return rule[key]


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
            MongoQueryBuilderBuildRuleError: If any other error occurs during rule creation - most
                commonly a value that cannot be coerced to the field's type (an unparsable date, or
                a non-numeric value on a number / reference field)
        """
        try:
            target_field: str = MDS_VALUES_PATH if field_name in self.mds_fields else FIELDS_PATH
            target_value = self._coerce_value(field_name, operator, value)

            return self._create_rule(target_field, operator, field_name, target_value)
        except MongoDBQueryBuilderError:
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
              # Ref-Section-Fields are rejected before a report's query is built
              # (report_helper.abort_if_ref_section_fields), so this arm is only reachable through
              # the type-update path that rebuilds the queries of already stored reports
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

        Everything but IS_NULL is a single `$elemMatch` against the field entry. IS_NULL additionally
        has to reach objects that carry no entry for the field at all - an `$elemMatch` can only ever
        match an entry that exists - so it becomes an `$or` of "entry exists and is empty" and "no
        such entry"

        Args:
            target_field (str): Document path to match against (FIELDS_PATH or MDS_VALUES_PATH)
            operator (str): The comparison operator of the rule
            field_name (str): The name of the field
            value (int | str | list[int] | list[str] | datetime | None): The (already coerced) value

        Returns:
            dict[str, Any]: The rule as a MongoDB compatible query part

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator was provided
        """
        entry_match: dict[str, Any] = {
            target_field: self._build_elem_match(field_name, self._get_value_fragment(operator, value))
        }

        if operator == ReportQueryOperator.IS_NULL:
            return {'$or': [entry_match, {target_field: {'$not': {'$elemMatch': {FIELD_NAME_KEY: field_name}}}}]}

        return entry_match


    @staticmethod
    def _build_elem_match(field_name: str, value_fragment: dict[str, Any]) -> dict[str, Any]:
        """
        Builds the `$elemMatch` selecting the named field entry and testing its value

        Args:
            field_name (str): The name of the field entry to select
            value_fragment (dict[str, Any]): The comparison applied to that entry's value

        Returns:
            dict[str, Any]: The `$elemMatch` fragment
        """
        return {'$elemMatch': {FIELD_NAME_KEY: field_name, FIELD_VALUE_KEY: value_fragment}}


    @staticmethod
    def _end_of_day(moment: datetime) -> datetime:
        """
        Returns the last representable instant of the given day

        Args:
            moment (datetime): Any instant on the wanted day

        Returns:
            datetime: The same day at 23:59:59.999999
        """
        return moment.replace(hour=23, minute=59, second=59, microsecond=999999)


    def _build_date_value_fragment(self, operator: str, value: datetime) -> dict[str, Any] | None:
        """
        Builds the day-granular comparison fragment for a date field, if the operator needs one

        A rule carries only a date (`YYYY-MM-DD`), which `_coerce_value` parses to that day's
        midnight, while the stored field holds a full timestamp. Comparing against midnight directly
        is only correct for `>=` and `<` (both of which mean "from / before the start of the day");
        the other comparisons have to be widened to the whole day, or they silently exclude
        everything that happened after 00:00:00 on it

        Args:
            operator (str): The comparison operator of the rule
            value (datetime): The parsed date, at midnight

        Returns:
            dict[str, Any] | None: The fragment, or None when the operator needs no widening and the
                caller should fall back to the direct mapping
        """
        day_start: datetime = value
        day_end: datetime = self._end_of_day(value)

        if operator == ReportQueryOperator.EQ:
            return {'$gte': day_start, '$lte': day_end}

        if operator == ReportQueryOperator.NE:
            return {'$not': {'$gte': day_start, '$lte': day_end}}

        if operator == ReportQueryOperator.LTE:
            return {'$lte': day_end}

        if operator == ReportQueryOperator.GT:
            return {'$gt': day_end}

        return None


    def _get_value_fragment(
        self,
        operator: str,
        value: int | str | list[int] | list[str] | datetime | None = None,
    ) -> dict[str, Any]:
        """
        Builds the value-comparison fragment for a single operator

        Only the fragment for the requested operator is constructed. A `datetime` value is compared
        day-granularly (see `_build_date_value_fragment`). ``contains`` and ``like`` match the value
        as a regular expression with the user input regex-escaped (so it is matched literally, never
        interpreted as a pattern); ``like`` additionally matches case-insensitively

        Note that `in` / `not in` over date values still compare the parsed midnights exactly. The
        report UI does not offer those operators for date fields, so widening them to a range of days
        was left unbuilt rather than guessed at

        Args:
            operator (str): The comparison operator (see ReportQueryOperator)
            value (int | str | list[int] | list[str] | datetime | None): The value of the condition

        Returns:
            dict[str, Any]: The value part of the condition

        Raises:
            MongoQueryBuilderInvalidOperatorError: When an unsupported operator is provided
        """
        if isinstance(value, datetime):
            date_fragment = self._build_date_value_fragment(operator, value)

            if date_fragment is not None:
                return date_fragment

        if operator in self.__DIRECT_OPERATORS:
            return {self.__DIRECT_OPERATORS[operator]: value}

        fragment_builder = self.__VALUE_FRAGMENT_BUILDERS.get(operator)

        if fragment_builder is not None:
            return fragment_builder(value)

        raise MongoQueryBuilderInvalidOperatorError(operator)
