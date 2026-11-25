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
Implementation of the rights on the access rules: field classes, scope roles and assignments
"""
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

class AccessRight(BaseRight):
    """
    Base class for the rights on the access rules
    """
    PREFIX: str = f'{BaseRight.PREFIX}.access'

# -------------------------------------------------------------------------------------------------------------------- #

class FieldClassRight(AccessRight):
    """
    Base class for the rights on the field classes
    """
    PREFIX: str = f'{AccessRight.PREFIX}.fieldclass'

# -------------------------------------------------------------------------------------------------------------------- #

class ScopeRoleRight(AccessRight):
    """
    Base class for the rights on the scope roles
    """
    PREFIX: str = f'{AccessRight.PREFIX}.scoperole'

# -------------------------------------------------------------------------------------------------------------------- #

class AssignmentRight(AccessRight):
    """
    Base class for the rights on the assignments
    """
    PREFIX: str = f'{AccessRight.PREFIX}.assignment'
