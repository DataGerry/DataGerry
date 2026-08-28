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
Constants for the CmdbUserGroup domain

``GroupKey`` enumerates the persisted top-level document keys of a CmdbUserGroup (collection
``management.groups``); the shared 'public_id' key is covered by CmdbObjectKey.PUBLIC_ID (the
project-wide precedent for document identity keys). The module further owns the public_ids of the
two bootstrap groups seeded by ``__FIXED_GROUPS__`` and the name of the master right, so that the
seeding, the manager guards and the route guards all read them from one place instead of repeating
the literals 1 / 2 / 'base.*'
"""
from cmdb.utils import BaseStrEnum

from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

# public_id of the bootstrap administrator group (seeded with the master right)
ADMIN_GROUP_ID: int = 1

# public_id of the bootstrap default user group
USER_GROUP_ID: int = 2

# Bootstrap groups which must not be deleted
PROTECTED_GROUP_IDS: tuple[int, ...] = (ADMIN_GROUP_ID, USER_GROUP_ID)

# Name of the master right ('base.*'), which grants every right in the tree via
# ``CmdbUserGroup.has_extended_right``. Removing it from the administrator group would leave nobody
# able to hand it back, so the update route refuses that change
MASTER_RIGHT_NAME: str = f'{BaseRight.PREFIX}.{GLOBAL_RIGHT_IDENTIFIER}'


class GroupKey(BaseStrEnum):
    """
    Persisted top-level document keys of a CmdbUserGroup
    """
    NAME = 'name'
    LABEL = 'label'
    RIGHTS = 'rights'
