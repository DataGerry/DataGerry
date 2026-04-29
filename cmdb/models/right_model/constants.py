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
Module for defining and mapping access right levels
"""
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

GLOBAL_RIGHT_IDENTIFIER = '*'

LEVEL_TO_NAME = {
    Levels.CRITICAL: 'CRITICAL',
    Levels.DANGER: 'DANGER',
    Levels.SECURE: 'SECURE',
    Levels.PROTECTED: 'PROTECTED',
    Levels.PERMISSION: 'PERMISSION',
    Levels.NOTSET: 'NOTSET',
}

NAME_TO_LEVEL = {
    'CRITICAL': Levels.CRITICAL,
    'DANGER': Levels.DANGER,
    'SECURE': Levels.SECURE,
    'PROTECTED': Levels.PROTECTED,
    'PERMISSION': Levels.PERMISSION,
    'NOTSET': Levels.NOTSET,
}
