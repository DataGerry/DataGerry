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
Shared constants for the export engine (framework layer)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# strftime format for the timestamp used in exported-file names, e.g. 2026_07_21-13_05_00. The stamp is
# taken in UTC (see export_filename_helper.build_export_filename_timestamp) and carries no timezone marker
EXPORT_FILENAME_TIMESTAMP_FMT: str = '%Y_%m_%d-%H_%M_%S'

# Import path prefix of the export format classes (dynamically loaded by class name via load_class)
EXPORT_FORMAT_MODULE_PREFIX: str = 'cmdb.framework.exporter.format.'


class ExporterExtensionKey(BaseStrEnum):
    """Keys of an export-format catalogue entry returned by `GET /exporter/extensions` (frontend contract)"""
    EXTENSION = 'extension'
    LABEL = 'label'
    ICON = 'icon'
    MULTI_TYPE_SUPPORT = 'multiTypeSupport'
    HELPER_TEXT = 'helperText'
    ACTIVE = 'active'


class ExporterOptionKey(BaseStrEnum):
    """Optional export parameters the format classes read from the request (`params.optional`)"""
    VIEW = 'view'
    METADATA = 'metadata'
    CLASSNAME = 'classname'  # the inner format the ZIP wrapper packs
    # Presentation ("human readable") export: replace column headers with field labels and resolve
    # reference / ref-section fields to their summary line and location fields to the location name
    HUMAN_READABLE = 'human_readable'
    # Resolved {location public_id -> location name} map the writer injects for HUMAN_READABLE exports
    # (the format classes have no database access, so the writer resolves the names and passes them in)
    LOCATION_NAMES = 'location_names'


class ExporterMetadataKey(BaseStrEnum):
    """Keys inside the `metadata` object that overrides the exported columns in the RENDER view"""
    HEADER = 'header'
    COLUMNS = 'columns'
