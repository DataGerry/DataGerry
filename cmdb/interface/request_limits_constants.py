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
How large a request, and the document it stores, may be

Three limits, each answered before anything is written:

* ``RequestSizeLimit.MAX_CONTENT_LENGTH`` is Flask's ``MAX_CONTENT_LENGTH`` for every request - Werkzeug answers
  413 for a larger body before the route reads it. Every single document the API stores is held to MongoDB's
  16 MB limit, so twice that leaves room for the bulk bodies that carry many documents
* the upload routes raise it for themselves (``route_utils.accepts_upload``): a file to import or to keep in the
  media library is a different order of size from a JSON body
* a write whose document would still exceed MongoDB's 16 MB limit is refused by the database layer with a typed
  ``DocumentTooLargeError``, which every route answers with the same 400 (``route_utils.abort_if_too_large``)
"""
# -------------------------------------------------------------------------------------------------------------------- #

MEBIBYTE: int = 1024 * 1024


class RequestSizeLimit:
    """The byte limits a request is held to"""
    #: Every request body, unless its route raises the limit for itself
    MAX_CONTENT_LENGTH: int = 32 * MEBIBYTE
    #: The body of an upload route: the object, type and ISMS imports and the media library
    UPLOAD_MAX_CONTENT_LENGTH: int = 128 * MEBIBYTE
    #: A non-file form field of the type import, which carries its whole upload as one JSON string. Werkzeug holds
    #: such a field in memory and caps it at 500 KB unless told otherwise
    TYPE_IMPORT_MAX_FORM_MEMORY_SIZE: int = 32 * MEBIBYTE


#: The 400 of a write whose document would exceed MongoDB's 16 MB document limit
DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE: str = (
    "The data is too large to be stored: a single document may not exceed MongoDB's 16 MB limit!"
)
