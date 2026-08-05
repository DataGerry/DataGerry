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
Implementation of all DocapiRights
"""
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class DocapiRight(BaseRight):
    """
    Base class for Docapi Rights

    Extends: BaseRight
    """
    MIN_LEVEL = Levels.PROTECTED
    PREFIX = f'{BaseRight.PREFIX}.docapi'

    def __init__(self, name: str, level: Levels = Levels.SECURE, description: str = None):
        super().__init__(level, name, description=description)


class DocapiTemplateRight(DocapiRight):
    """
    Class for DocapiTemplate Rights

    Extends: DocapiRight
    """
    MIN_LEVEL = Levels.PROTECTED
    PREFIX = f'{DocapiRight.PREFIX}.template'

    def __init__(self, name: str, level: Levels = Levels.SECURE, description: str = None):
        super().__init__(name, level, description=description)
