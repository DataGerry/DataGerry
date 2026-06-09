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
Response-shape constants for the CmdbType REST routes

Names the dict keys of the ``/rest/types/with_clean_status`` response items and their nested
user-data block, so the route helpers build that response from one set of named keys instead of
repeating the literals.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class TypeCleanStatusKey(BaseStrEnum):
    """
    Keys of a single item in the ``/rest/types/with_clean_status`` response

    TYPE_DATA holds the CmdbType document, USER_DATA the resolved author/editor block (see
    TypeUserDataKey) and CLEAN_STATUS whether every object of the type matches its field set.
    """
    TYPE_DATA = 'type_data'
    USER_DATA = 'user_data'
    CLEAN_STATUS = 'clean_status'


class TypeUserDataKey(BaseStrEnum):
    """
    Keys of the resolved author / editor block returned alongside a CmdbType

    Each holds the display name or profile image of the type's author / last editor, or None when
    the referenced CmdbUser could not be resolved.
    """
    AUTHOR = 'author'
    AUTHOR_IMAGE = 'author_image'
    LAST_EDITOR = 'last_editor'
    LAST_EDITOR_IMAGE = 'last_editor_image'
