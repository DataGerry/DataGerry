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
Shared constants for the CmdbObject export REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The 'zip' export packs an underlying format, so its class is a valid dynamic-load target too
ZIP_EXPORT_FORMAT: str = 'ZipExportFormat'

# Export format used when the request does not specify a 'classname'
DEFAULT_EXPORT_FORMAT: str = 'JsonExportFormat'

# Mimetype + file extension of the CmdbType export (JSON only)
TYPE_EXPORT_MIMETYPE: str = 'application/json'
TYPE_EXPORT_FILE_EXTENSION: str = 'json'


class ExporterQueryParam(BaseStrEnum):
    """Query-parameter keys consumed by the object-export route"""
    ZIP = 'zip'
    CLASSNAME = 'classname'
