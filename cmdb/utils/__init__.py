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
Project-wide, domain-unspecific Python helpers and definitions

Domain helpers (CmdbObject-document helpers, IPAM CIDR helpers, etc.) live next to their
domain. This package is the explicit home for cross-feature, language-level utilities such
as the shared BaseStrEnum, cast helpers, logging configuration, and decorator wrappers
"""
from .base_str_enum import BaseStrEnum
from .validation_error import ValidationErrorKey, build_error
# -------------------------------------------------------------------------------------------------------------------- #


__all__: list[str] = [
    'BaseStrEnum',
    'ValidationErrorKey',
    'build_error',
]
