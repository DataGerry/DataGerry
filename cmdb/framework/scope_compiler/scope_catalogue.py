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
The scope builder's catalogue (phase 9, ruled R30): what a scope may say, read from the code so the frontend cannot
drift from it - the operators per field kind, which operators take no value / a list / a pair, the one-key blocks, the
user tokens and where they stand, the relative date key, the caps
"""
from typing import Any

from cmdb.utils import BaseStrEnum

from cmdb.framework.scope_compiler.scope_compiler_constants import (
    KIND_OPERATORS,
    LIST_OPERATORS,
    MAX_DAYS_AGO,
    MAX_LIST_VALUES,
    MAX_SCOPE_BLOCKS,
    MAX_TEXT_LENGTH,
    MULTIPLE_PERSON_KIND,
    NO_VALUE_OPERATORS,
    PAIR_OPERATORS,
    RELATION_FILTER_KEY,
    TOKEN_OPERATORS,
    RelativeDateKey,
    ScopeBlockKind,
    ScopeOperator,
    UserToken,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CatalogueKey',
    'scope_catalogue',
]


class CatalogueKey(BaseStrEnum):
    """
    The keys of the catalogue answer
    """
    OPERATORS = 'operators'
    KIND_OPERATORS = 'kind_operators'
    MULTIPLE_PERSON_KIND = 'multiple_person_kind'
    NO_VALUE_OPERATORS = 'no_value_operators'
    LIST_OPERATORS = 'list_operators'
    PAIR_OPERATORS = 'pair_operators'
    BLOCKS = 'blocks'
    TOKENS = 'tokens'
    RELATED_TO_FILTER = 'related_to_filter'
    TOKEN_OPERATORS = 'token_operators'
    RELATIVE_DATE_KEY = 'relative_date_key'
    LIMITS = 'limits'
    MAX_CONDITIONS = 'conditions'
    MAX_LIST_VALUES = 'list_values'
    MAX_TEXT_LENGTH = 'text_length'
    MAX_DAYS_AGO = 'days_ago'


def _ordered(operators: frozenset[ScopeOperator]) -> list[str]:
    """
    Operator values in ScopeOperator order

    Args:
        operators (frozenset[ScopeOperator]): The operators

    Returns:
        list[str]: Their values
    """
    return [operator.value for operator in ScopeOperator if operator in operators]


def scope_catalogue() -> dict[str, Any]:
    """
    The catalogue answer

    Returns:
        dict[str, Any]: What a scope may say, ordered for display
    """
    return {
        CatalogueKey.OPERATORS.value: [operator.value for operator in ScopeOperator],
        CatalogueKey.KIND_OPERATORS.value: {kind: _ordered(operators) for kind, operators in KIND_OPERATORS.items()},
        CatalogueKey.MULTIPLE_PERSON_KIND.value: MULTIPLE_PERSON_KIND,
        CatalogueKey.NO_VALUE_OPERATORS.value: _ordered(NO_VALUE_OPERATORS),
        CatalogueKey.LIST_OPERATORS.value: _ordered(LIST_OPERATORS),
        CatalogueKey.PAIR_OPERATORS.value: _ordered(PAIR_OPERATORS),
        CatalogueKey.BLOCKS.value: [kind.value for kind in ScopeBlockKind],
        CatalogueKey.RELATED_TO_FILTER.value: RELATION_FILTER_KEY,
        CatalogueKey.TOKENS.value: [token.value for token in UserToken],
        CatalogueKey.TOKEN_OPERATORS.value: _ordered(TOKEN_OPERATORS),
        CatalogueKey.RELATIVE_DATE_KEY.value: RelativeDateKey.DAYS_AGO.value,
        CatalogueKey.LIMITS.value: {
            CatalogueKey.MAX_CONDITIONS.value: MAX_SCOPE_BLOCKS,
            CatalogueKey.MAX_LIST_VALUES.value: MAX_LIST_VALUES,
            CatalogueKey.MAX_TEXT_LENGTH.value: MAX_TEXT_LENGTH,
            CatalogueKey.MAX_DAYS_AGO.value: MAX_DAYS_AGO,
        },
    }
