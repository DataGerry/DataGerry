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
# taken in UTC (see export_filename_helper.build_export_filename_timestamp) and carries no timezone marker.
# The date leads so a downloads folder sorts chronologically by name
EXPORT_FILENAME_TIMESTAMP_FMT: str = '%Y_%m_%d-%H_%M_%S'

# The parts an export filename is assembled from, after the timestamp:
#   <timestamp>_<kind>_<subject>[_readable].<extension>
# e.g. `2026_07_21-13_05_00_objects_router_readable.csv`, `2026_07_21-13_05_00_types_47.json`
EXPORT_FILENAME_PART_SEPARATOR: str = '_'

# What was exported - the two export kinds name themselves so an object export and a type export taken in
# the same second are no longer indistinguishable
EXPORT_KIND_OBJECTS: str = 'objects'
EXPORT_KIND_TYPES: str = 'types'

# Subject of an object export when the selection is not one single type: JSON / XML / ZIP may span several
# types (CSV and XLSX refuse a mixed selection), and a filter can match nothing at all
EXPORT_SUBJECT_MANY_TYPES_TEMPLATE: str = '{count}-types'
EXPORT_SUBJECT_NO_OBJECTS: str = 'no-objects'

# Appended to a presentation ("human readable") export. Such a file is NOT re-importable, so the name says
# so - it is the cheapest guard against feeding one back into the importer later
EXPORT_FILENAME_READABLE_MARKER: str = 'readable'

# Closes the name of an object-import template, which carries no data at all: only the header row a user
# fills in. The type is named by its LABEL here (an export names it by its type name), because a template
# is a document handed to a person
EXPORT_FILENAME_TEMPLATE_MARKER: str = 'template'

# A filename part is reduced to these characters; everything else becomes the replacement. CmdbType names
# are free text, and the value ends up in a Content-Disposition header as well as on a filesystem
EXPORT_FILENAME_ALLOWED_PATTERN: str = r'[^a-z0-9.-]+'
EXPORT_FILENAME_REPLACEMENT: str = '-'

# Length caps: the subject alone, and the assembled name without its extension
EXPORT_FILENAME_SUBJECT_MAX_LENGTH: int = 40
EXPORT_FILENAME_MAX_LENGTH: int = 120

# Import path prefix of the export format classes (dynamically loaded by class name via load_class)
EXPORT_FORMAT_MODULE_PREFIX: str = 'cmdb.framework.exporter.format.'

# Layout of one column header in an object-import template. A column reads
#   `<Field label> [MDS-<Section label>] [<field name>]`
# with the MDS part present only for a field of a multi-data-section. The label leads because the file is
# filled in by a person; the bracketed field name closes it because that is the identifier the import
# needs, and naming the MDS section (rather than a bare marker) keeps two multi-data-sections apart
TEMPLATE_MDS_MARKER_TEMPLATE: str = '[MDS-{section}]'
TEMPLATE_FIELD_NAME_TEMPLATE: str = '[{name}]'
TEMPLATE_COLUMN_PART_SEPARATOR: str = ' '

# Labels of the two identity columns an import template leads with. They are CmdbObject properties, not
# CmdbType fields, so there is no label to read from the type
TEMPLATE_PUBLIC_ID_LABEL: str = 'Public ID'
TEMPLATE_ACTIVE_LABEL: str = 'Active'


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
