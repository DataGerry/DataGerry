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
Constants for the CmdbObject REST routes

Holds the named values shared across the object routes and their helper so the routes never
compare against bare string literals
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ObjectViewMode(BaseStrEnum):
    """
    Accepted values of the ``view`` query parameter on the object list / reference routes

    Selects how each CmdbObject is serialised in the response: ``NATIVE`` returns the stored
    document as-is, ``RENDER`` returns the rendered (display) representation
    """
    NATIVE = 'native'
    RENDER = 'render'


class ObjectPatchKey(BaseStrEnum):
    """
    The only keys accepted in a partial-update (PATCH) object payload

    A PATCH body may carry a subset of regular ``FIELDS`` plus three symmetric MDS-row lists:
    ``CREATED_MDS_ROWS`` (the backend assigns each new row's multi_data_id and bumps the section
    counter), ``EDITED_MDS_ROWS`` and ``DELETED_MDS_ROWS``, and an optional ``COMMENT`` for the
    edit log. Any other key (an immutable identifier or a server-managed field) is rejected so
    clients cannot silently attempt to change it
    """
    FIELDS = 'fields'
    CREATED_MDS_ROWS = 'created_mds_rows'
    EDITED_MDS_ROWS = 'edited_mds_rows'
    DELETED_MDS_ROWS = 'deleted_mds_rows'
    COMMENT = 'comment'
