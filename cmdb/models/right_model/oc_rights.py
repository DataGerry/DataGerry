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
Implementation of rights regarding OpenCelium interaction
"""
from cmdb.models.right_model.base_right import BaseRight, DefaultLevelRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class OpenCeliumRight(DefaultLevelRight):
    """
    Base class for general OpenCelium rights
    """
    MIN_LEVEL = Levels.PERMISSION
    PREFIX = f'{BaseRight.PREFIX}.openCelium'

# -------------------------------------------------------------------------------------------------------------------- #

class OcConnectorRight(OpenCeliumRight):
    """
    Base class for OcConnector rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX: str = f'{OpenCeliumRight.PREFIX}.connector'


class OcConnectionRight(OpenCeliumRight):
    """
    Base class for OcConnection rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX: str = f'{OpenCeliumRight.PREFIX}.connection'
