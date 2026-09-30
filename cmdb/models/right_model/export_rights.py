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
Implementation of all ExportRights
"""
from cmdb.models.right_model.base_right import BaseRight, DefaultLevelRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class ExportRight(DefaultLevelRight):
    """
    Base class for Export Rights

    Extends: BaseRight
    """
    MIN_LEVEL = Levels.PROTECTED
    PREFIX = f'{BaseRight.PREFIX}.export'
    DEFAULT_LEVEL = Levels.SECURE


class ExportObjectRight(ExportRight):
    """
    Class for exporting objects Rights
    
    Extends: ExportRight
    """
    MIN_LEVEL = Levels.PROTECTED
    PREFIX = f'{ExportRight.PREFIX}.object'
    DEFAULT_LEVEL = Levels.SECURE


class ExportTypeRight(ExportRight):
    """
    Class for exporting types Rights
    
    Extends: ExportRight
    """
    MIN_LEVEL = Levels.SECURE
    PREFIX = f'{ExportRight.PREFIX}.type'
