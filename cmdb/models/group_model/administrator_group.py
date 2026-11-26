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
Who is an administrator: a member of the administrator group. One answer for the user management guards and the
access rule guards, which exempt administrators so they can always re-grant themselves
"""
from collections.abc import Iterable

from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
# -------------------------------------------------------------------------------------------------------------------- #


def in_administrator_group(group_ids: Iterable[int]) -> bool:
    """
    Whether a user's groups include the administrator group

    Args:
        group_ids (Iterable[int]): The user's ``group_ids``

    Returns:
        bool: True for a member of ``ADMIN_GROUP_ID``
    """
    return ADMIN_GROUP_ID in set(group_ids)
