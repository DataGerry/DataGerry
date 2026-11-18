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
Implementation of all Importer Rights
"""
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

class ImportRight(BaseRight):
    """
    Base class for Importer rights
    """
    PREFIX = f'{BaseRight.PREFIX}.import'


class ImportObjectRight(ImportRight):
    """
    Right class for importing CmdbObjects
    """
    PREFIX = f'{ImportRight.PREFIX}.object'


class ImportTypeRight(ImportRight):
    """
    Right class for importing CmdbTypes
    """
    PREFIX = f'{ImportRight.PREFIX}.type'
