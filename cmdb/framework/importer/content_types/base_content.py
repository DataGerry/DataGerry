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
Basic identifiers for the identification of the corresponding importers based on the file type.
The Content-Type entity header is used to indicate the media type of the resource.
"""
# -------------------------------------------------------------------------------------------------------------------- #

class BaseContent:
    """
    Empty base content-type identifier

    Holds the slots (icon, content type, file type) that concrete content types fill; not intended
    to be used directly.
    """
    ICON: str = ''
    CONTENT_TYPE: str = ''
    FILE_TYPE: str = ''
