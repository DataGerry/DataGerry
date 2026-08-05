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
This module provides the predefined CmdbExtendableOptions required for ISMS
"""
from typing import Any

from cmdb.models.extendable_option_model import OptionType
from cmdb.database.predefined_data.predefined_data_constants import ExtendableOptionKey
# -------------------------------------------------------------------------------------------------------------------- #

def get_default_isms_extendable_options() -> list[dict[str, Any]]:
    """
    Returns the predefined CmdbExtendableOptions for ISMS, inserted at setup

    Currently the IMPLEMENTATION_STATE options (None / Open / In Progress / Implemented).

    Returns:
        list[dict[str, Any]]: The default ISMS CmdbExtendableOptions as documents
    """
    return [
        {
            ExtendableOptionKey.VALUE: 'None',
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: 'Open',
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: 'In Progress',
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: 'Implemented',
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        }
    ]
