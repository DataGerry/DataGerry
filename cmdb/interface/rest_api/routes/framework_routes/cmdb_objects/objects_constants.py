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
compare against bare string literals. The CmdbObject document's own keys are NOT here - they belong to
the model (``CmdbObjectKey`` in ``cmdb.models.object_model``); what lives here is what belongs to the
REST surface: query parameters, response keys and the routes' own limits
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MAX_DASHBOARD_GROUPS',
    'ObjectViewMode',
    'ObjectPatchKey',
    'ObjectQueryParam',
    'ObjectGroupKey',
    'BulkDeleteKey',
]

# Maximum number of type groups returned for the dashboard chart by the group-by route. The chart shows
# the biggest groups only, so the route stops collecting once it has this many
MAX_DASHBOARD_GROUPS: int = 5


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
    counter), ``EDITED_MDS_ROWS`` and ``DELETED_MDS_ROWS``, an optional ``COMMENT`` for the edit
    log, and an optional ``LOCATION_NAME`` (the custom CmdbLocation tree name; the parent itself is
    patched through the location field in ``FIELDS``). Any other key (an immutable identifier or a
    server-managed field) is rejected so clients cannot silently attempt to change it
    """
    FIELDS = 'fields'
    CREATED_MDS_ROWS = 'created_mds_rows'
    EDITED_MDS_ROWS = 'edited_mds_rows'
    DELETED_MDS_ROWS = 'deleted_mds_rows'
    COMMENT = 'comment'
    LOCATION_NAME = 'location_name'


class ObjectQueryParam(BaseStrEnum):
    """
    Query parameters the object routes read directly off the request

    ``OBJECT_IDS`` is accepted in two encodings, one per route, because that is what the frontend
    sends: the bulk update reads REPEATED parameters (`objectIDs=1&objectIDs=2`, what Angular produces
    from an array of params) while the MDS-references route reads ONE comma-joined value
    (`objectIDs=1,2`, what `HttpParams.set` produces). Unifying them is a frontend-visible change
    """
    OBJECT_IDS = 'objectIDs'


class ObjectGroupKey(BaseStrEnum):
    """
    Keys of one group returned by the dashboard group-by route

    ``ID`` is MongoDB's own grouping key; ``LABEL`` and ``TYPE_COLOR`` are added by the route from the
    group's CmdbType so the chart can render a group without resolving the type itself
    """
    ID = '_id'
    LABEL = 'label'
    TYPE_COLOR = 'type_color'


class BulkDeleteKey(BaseStrEnum):
    """Keys of the bulk-delete response body"""
    SUCCESSFULLY = 'successfully'
