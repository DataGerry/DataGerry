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
Shared constants for the import REST routes

The form fields and the config keys belong to the CmdbObject import; ImporterRight covers the whole
package, since the right an import route checks is the one thing every module here has
"""
from cmdb.utils import BaseStrEnum
from cmdb.framework.importer.importer_constants import IMPORTER_KIND_OBJECT
# -------------------------------------------------------------------------------------------------------------------- #

# Re-exported from the framework layer so the route and the importer registry share one source of truth
__all__: list[str] = [
    'IMPORTER_KIND_OBJECT',
    'ImporterFormField',
    'ImporterConfigKey',
    'ImporterRight',
    'NO_CONTENT_TO_IMPORT_MESSAGE',
]

# Answer for a file that parsed correctly but carries no data row - a header-only CSV, which is what a
# freshly downloaded import template is. Shared by the parse-preview and the import route so both name the
# real reason instead of blaming the parser configuration
NO_CONTENT_TO_IMPORT_MESSAGE: str = (
    "The file contains no data rows to import - only its header. Fill the file in and upload it again!"
)


class ImporterFormField(BaseStrEnum):
    """Multipart form-field names read from an object-import request"""
    FILE = 'file'
    FILE_FORMAT = 'file_format'
    PARSER_CONFIG = 'parser_config'
    IMPORTER_CONFIG = 'importer_config'


class ImporterConfigKey(BaseStrEnum):
    """
    Keys read from the importer configuration payload

    START_ELEMENT / MAX_ELEMENTS bound the batch and are validated by the route: both are counts, so
    a negative value is not a smaller batch but a different one (a negative start would slice from
    the END of the candidate list)
    """
    TYPE_ID = 'type_id'
    START_ELEMENT = 'start_element'
    MAX_ELEMENTS = 'max_elements'


class ImporterRight(BaseStrEnum):
    """
    ACL right identifiers guarding the import REST routes

    One member per import surface. The object and type imports are guarded by their family's wildcard
    ('*' = every right below that prefix) because neither splits its surface further; the ISMS import
    names one concrete right, since the ISMS tree separates add from the rest. The values mirror
    ImportObjectRight / ImportTypeRight / IsmsImportRight in the right model - a value that does not
    exist there denies every caller, which is why they are written down once here instead of being
    spelled at each route
    """
    OBJECT = 'base.import.object.*'
    TYPE = 'base.import.type.*'
    ISMS_ADD = 'base.isms.import.add'
