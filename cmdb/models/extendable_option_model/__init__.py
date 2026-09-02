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
Provides all CmdbExtendableOption relevant classes and constants
"""
from .option_type_enum import OptionType
from .extendable_option_constants import (
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
    LEGACY_OPTION_TYPE_INDEX_NAME,
)
from .cmdb_extendable_option import CmdbExtendableOption
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'OptionType',
    'ExtendableOptionKey',
    'OPTION_TYPE_VALUE_INDEX_NAME',
    'LEGACY_OPTION_TYPE_INDEX_NAME',
    'CmdbExtendableOption',
]
