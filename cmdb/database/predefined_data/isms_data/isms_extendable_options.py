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

from cmdb.models.extendable_option_model import OptionType, ExtendableOptionKey
from cmdb.models.isms_model.implementation_state_enum import ImplementationState
# -------------------------------------------------------------------------------------------------------------------- #

def get_default_isms_extendable_options() -> list[dict[str, Any]]:
    """
    Returns the predefined CmdbExtendableOptions for ISMS, inserted at setup

    Currently the IMPLEMENTATION_STATE options, whose values are named by `ImplementationState` -
    the risk-matrix report resolves IMPLEMENTED by value, so the two may not drift apart.

    Returns:
        list[dict[str, Any]]: The default ISMS CmdbExtendableOptions as documents
    """
    return [
        {
            ExtendableOptionKey.VALUE: ImplementationState.NONE.value,
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: ImplementationState.OPEN.value,
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: ImplementationState.IN_PROGRESS.value,
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        },
        {
            ExtendableOptionKey.VALUE: ImplementationState.IMPLEMENTED.value,
            ExtendableOptionKey.OPTION_TYPE: OptionType.IMPLEMENTATION_STATE,
            ExtendableOptionKey.PREDEFINED: True,
        }
    ]
