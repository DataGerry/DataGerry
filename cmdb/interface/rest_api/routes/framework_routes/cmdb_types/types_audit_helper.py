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
The audit keys of a CmdbType write: who created it and when, who edited it last and when

All four are the server's. ``TYPE_WRITE_SCHEMA`` drops them from a request body, so a client's values never reach
these stampers; the create stamps the caller and the clock and leaves the edit half empty, and the update keeps the
stored author and creation time and stamps the caller as the editor. The type import does the same on its own path
(``importer_type_helper.stamp_import_authorship`` / ``stamp_import_edit``)
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'stamp_type_create_audit',
    'stamp_type_update_audit',
]


def stamp_type_create_audit(data: dict[str, Any], request_user: CmdbUser) -> None:
    """
    Stamps the audit keys of a new CmdbType, in place

    The caller is the author and now the creation time; a new Type has never been edited, so the editor and the
    edit time are null - the values the type import's create stores too

    Args:
        data (dict[str, Any]): The validated create payload, edited in place
        request_user (CmdbUser): The CmdbUser creating the Type
    """
    data[TypeSchemaKey.AUTHOR_ID.value] = request_user.public_id
    data[TypeSchemaKey.CREATION_TIME.value] = datetime.now(timezone.utc)
    data[TypeSchemaKey.LAST_EDIT_TIME.value] = None
    data[TypeSchemaKey.EDITOR_ID.value] = None


def stamp_type_update_audit(data: dict[str, Any], stored_type: CmdbType, request_user: CmdbUser) -> None:
    """
    Stamps the audit keys of an updated CmdbType, in place

    The author and the creation time describe how the Type came to exist, so they are the stored ones - an update
    is written wholesale, and without them the Type would lose both. The caller is the editor and now the edit time

    Args:
        data (dict[str, Any]): The validated update payload, edited in place
        stored_type (CmdbType): The Type as stored before the update
        request_user (CmdbUser): The CmdbUser updating the Type
    """
    data[TypeSchemaKey.AUTHOR_ID.value] = stored_type.author_id
    data[TypeSchemaKey.CREATION_TIME.value] = stored_type.creation_time
    data[TypeSchemaKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)
    data[TypeSchemaKey.EDITOR_ID.value] = request_user.public_id
