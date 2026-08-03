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

Names the dict keys of the ``/rest/types/overview`` response items and their nested user-data block,
so the route helpers build that response from one set of named keys instead of repeating the literals.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Message returned when a CmdbType lookup by public_id finds nothing (HTTP 404). Shared by every
# "look it up or 404" helper so a missing type reads the same wherever it is reported
TYPE_NOT_FOUND_MESSAGE: str = 'The Type with ID:{public_id} was not found!'


class TypeOverviewKey(BaseStrEnum):
    """
    Keys of a single item in the ``/rest/types/overview`` response

    TYPE_DATA holds the CmdbType document and USER_DATA the resolved author/editor block (see
    TypeUserDataKey).
    """
    TYPE_DATA = 'type_data'
    USER_DATA = 'user_data'


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
