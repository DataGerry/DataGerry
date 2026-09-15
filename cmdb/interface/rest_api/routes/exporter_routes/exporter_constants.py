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
Shared constants for the export REST routes

The format constants and query parameters cover only the object export, which is driven by the export
engine in `cmdb/framework/exporter`; the CmdbType export has its own module, `exporter_type_constants`.
ExporterRight spans the package, since the right an export route checks is the one thing both modules
have
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ZIP_EXPORT_FORMAT',
    'DEFAULT_EXPORT_FORMAT',
    'ExporterQueryParam',
    'ExporterRight',
]

# The 'zip' export packs an underlying format, so its class is a valid dynamic-load target too
ZIP_EXPORT_FORMAT: str = 'ZipExportFormat'

# Export format used when the request does not specify a 'classname'
DEFAULT_EXPORT_FORMAT: str = 'JsonExportFormat'


class ExporterQueryParam(BaseStrEnum):
    """Query-parameter keys consumed by the object-export route"""
    ZIP = 'zip'
    CLASSNAME = 'classname'


class ExporterRight(BaseStrEnum):
    """
    ACL right identifiers guarding the export REST routes

    Both surfaces are guarded by their family's wildcard ('*' = every right below that prefix), neither
    splitting further. The values mirror ExportObjectRight / ExportTypeRight in the right model - a
    value that does not exist there denies every caller, which is why they are written down once here
    instead of being spelled at each route
    """
    OBJECT = 'base.export.object.*'
    TYPE = 'base.export.type.*'
