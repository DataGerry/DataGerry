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

    **Who holds them:** nobody by default. The seeded `user` group carries neither, so a default user
    may read objects and types and may not export them - reading a thing and taking it away as a file
    are different permissions, and a type export additionally carries every Type's stored `acl` block.
    Decided 2026-09-21 (discussion-backlog #38); until 2026-07-23 the object export asked for
    `base.framework.object.view` instead, which that group does hold. The audience is pinned by
    tests/functional/framework/test_functional_export_rights.py, and stated in `workflows/rights.md`

    Note the IPAM overview CSVs and the DocAPI render answer the same question differently - they are
    guarded by the feature's own view right, on the grounds that whoever may read the view may take it
    away as a file. That the three export-shaped surfaces disagree is filed, not settled
    """
    OBJECT = 'base.export.object.*'
    TYPE = 'base.export.type.*'
