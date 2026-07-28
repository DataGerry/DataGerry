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
Shared constants for the CmdbObject import REST routes
"""
from cmdb.utils import BaseStrEnum
from cmdb.framework.importer.importer_constants import IMPORTER_KIND_OBJECT
# -------------------------------------------------------------------------------------------------------------------- #

# Re-exported from the framework layer so the route and the importer registry share one source of truth
__all__: list[str] = ['IMPORTER_KIND_OBJECT', 'ImporterFormField', 'ImporterConfigKey']


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
