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
Shared constants describing a CmdbReport document, its condition rule tree and its query DSL

``ReportKey`` names the stored document's keys, and ``ReportCategoryKey`` those of a CmdbReportCategory - each
model, its validation schema, the managers and the routes all spell them through them.

A report stores its filter as a nested condition tree. Each node is either a group (combining its
child rules with a logical operator, see ReportConditionLogic) or a leaf rule (pairing a field name
with a comparison operator, see ReportQueryOperator, and a value). These enums name the dict keys,
the logical group operators and the comparison operators of that structure so both the REST layer
(reading / validating the request) and the database layer (MongoDBQueryBuilder, translating the tree
into a Mongo query) reference the same literals from one place. All extend BaseStrEnum, so members
compare and serialize as their string values.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ReportKey(BaseStrEnum):
    """
    Keys of a stored CmdbReport document

    The model reads and writes them, the validation schema declares them, the managers query by them, and a report
    request body uses the same keys. Use these members instead of bare string literals so a typo becomes an
    AttributeError instead of a silently missing key
    """
    PUBLIC_ID = 'public_id'
    REPORT_CATEGORY_ID = 'report_category_id'
    NAME = 'name'
    TYPE_ID = 'type_id'
    SELECTED_FIELDS = 'selected_fields'
    CONDITIONS = 'conditions'
    REPORT_QUERY = 'report_query'
    PREDEFINED = 'predefined'
    MDS_MODE = 'mds_mode'


class ReportCategoryKey(BaseStrEnum):
    """
    Keys of a stored CmdbReportCategory document

    The model reads and writes them (as its ``KEYS``, so the shared CmdbDAO from_data / to_json serve it), the
    validation schema declares them, the database bootstrap seeds the predefined 'General' category with them and the
    configuration reset selects by them. A category request body uses the same keys
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    PREDEFINED = 'predefined'


class ReportQueryKey(BaseStrEnum):
    """
    Keys of a CmdbReport's stored 'report_query'

    DATA holds the serialized Mongo query string rebuilt from the report's conditions. Lives with the
    model constants rather than the route ones because the ReportsManager rebuilds a stored query too
    """
    DATA = 'data'


class ReportConditionKey(BaseStrEnum):
    """
    Keys of one node in a report's 'conditions' rule tree

    A node is either a group carrying CONDITION + RULES (nested groups) or a leaf carrying FIELD
    (the referenced field name) together with OPERATOR and VALUE
    """
    CONDITION = 'condition'
    RULES = 'rules'
    FIELD = 'field'
    OPERATOR = 'operator'
    VALUE = 'value'


class ReportConditionLogic(BaseStrEnum):
    """
    Logical operators combining the child rules of a condition group

    The 'condition' of a group node is one of these, deciding whether its child rules are AND-ed or
    OR-ed together
    """
    AND = 'and'
    OR = 'or'


class ReportQueryOperator(BaseStrEnum):
    """
    Comparison operators a leaf rule of a report's condition tree may use

    The 'operator' of a leaf rule is one of these; MongoDBQueryBuilder maps each to its MongoDB
    equivalent when building the report query
    """
    EQ = '='
    NE = '!='
    LTE = '<='
    GTE = '>='
    LT = '<'
    GT = '>'
    IN = 'in'
    NOT_IN = 'not in'
    CONTAINS = 'contains'
    LIKE = 'like'
    IS_NULL = 'is null'
    IS_NOT_NULL = 'is not null'
