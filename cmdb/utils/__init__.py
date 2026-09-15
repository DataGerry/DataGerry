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
Project-wide, domain-unspecific Python helpers and definitions

Domain helpers (CmdbObject-document helpers, IPAM CIDR helpers, etc.) live next to their
domain. This package is the explicit home for cross-feature, language-level utilities such
as the shared BaseStrEnum, cast helpers and logging configuration

Everything listed in `__all__` is imported from the package path (`from cmdb.utils import ...`),
not from the module inside it - with one exception: a module *inside* this package imports its
siblings by module path, since going through the package here would be a cyclic import. Three names
are deliberately left out of `__all__`: `boolify` and `noneify` are `auto_cast`'s individual casters
rather than an API of their own, and `cmdb.utils.logger` is process bootstrap that callers import by
module path.

`cmdb.utils.wraps` used to sit beside it, holding a `@deprecated` decorator that was applied to
nothing in the whole repository - the only `@deprecated` uses were the examples inside its own
docstring. Removed 2026-09-14
"""
from .base_str_enum import BaseStrEnum
from .cast import auto_cast
from .helpers import (
    MONGO_DATE_KEY,
    coerce_datetime,
    coerce_document_dates,
    coerce_empty_document_values,
    coerce_mongo_datetime,
    coerce_whole_number,
    duplicate_names,
    is_hex_color,
    is_non_blank_string,
    is_truthy_query_arg,
    load_class,
    parse_import_bool,
    process_bar,
    random_hex_color,
    str_to_bool,
)
from .validation_error import ValidationErrorKey, build_error
# -------------------------------------------------------------------------------------------------------------------- #


__all__: list[str] = [
    'BaseStrEnum',
    'MONGO_DATE_KEY',
    'ValidationErrorKey',
    'auto_cast',
    'build_error',
    'coerce_datetime',
    'coerce_document_dates',
    'coerce_empty_document_values',
    'coerce_mongo_datetime',
    'coerce_whole_number',
    'duplicate_names',
    'is_hex_color',
    'is_non_blank_string',
    'is_truthy_query_arg',
    'load_class',
    'parse_import_bool',
    'process_bar',
    'random_hex_color',
    'str_to_bool',
]
