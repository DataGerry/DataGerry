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
Implementation of OptionType
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class OptionType(BaseStrEnum):
    """
    Available OptionTypes for CmdbExtendableOptions
    """
    OBJECT_GROUP = 'OBJECT_GROUP'
    THREAT_VULNERABILITY = 'THREAT_VULNERABILITY'
    IMPLEMENTATION_STATE = 'IMPLEMENTATION_STATE'
    CONTROL_MEASURE = 'CONTROL_MEASURE'
    RISK = 'RISK'
    PORT_STATUS = 'PORT_STATUS'
    PORT_TYPE = 'PORT_TYPE'
    PORT_SPEED = 'PORT_SPEED'
    CABLE_TYPE = 'CABLE_TYPE'
