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
Implementation of rights regarding the on-premise license feature
"""
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

class LicenseRight(BaseRight):
    """
    Base class for general license rights
    """
    PREFIX = f'{BaseRight.PREFIX}.license'

# -------------------------------------------------------------------------------------------------------------------- #

class LicenseActivationRight(LicenseRight):
    """
    Base class for license activation-request rights
    """
    PREFIX: str = f'{LicenseRight.PREFIX}.activation'
