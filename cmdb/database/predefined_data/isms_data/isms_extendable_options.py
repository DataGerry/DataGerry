# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This package provides all predefined data for CmdbExtendableOptions required for ISMS
"""
from cmdb.models.extendable_option_model import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

def get_default_isms_extendable_options() -> list:
    """
    All predefined CmdbExtendableOptions as data. Used when DataGerry is setup

    Returns:
        list: All default CmdbExtendableOptions for ISMS as data
    """
    return [
        {
            'value': 'None',
            'option_type': OptionType.IMPLEMENTATION_STATE,
            'predefined': True,
        },
        {
            'value': 'Open',
            'option_type': OptionType.IMPLEMENTATION_STATE,
            'predefined': True,
        },
        {
            'value': 'In Progress',
            'option_type': OptionType.IMPLEMENTATION_STATE,
            'predefined': True,
        },
        {
            'value': 'Implemented',
            'option_type': OptionType.IMPLEMENTATION_STATE,
            'predefined': True,
        }
    ]
