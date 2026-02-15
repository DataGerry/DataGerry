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
This package provides all predefined data for CmdbDAO subclasses
"""
from .isms_risk_matrix_data import get_default_risk_matrix
from .isms_extendable_options import get_default_isms_extendable_options
from .isms_protection_goals import get_default_protection_goals
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'get_default_risk_matrix',
    'get_default_isms_extendable_options',
    'get_default_protection_goals',
]
