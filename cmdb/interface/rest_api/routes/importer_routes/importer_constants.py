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
# -------------------------------------------------------------------------------------------------------------------- #

# Importer/parser kind resolved by the importer helper registry (only 'object' imports exist today)
IMPORTER_KIND_OBJECT: str = 'object'


class ImporterFormField(BaseStrEnum):
    """Multipart form-field names read from an object-import request"""
    FILE = 'file'
    FILE_FORMAT = 'file_format'
    PARSER_CONFIG = 'parser_config'
    IMPORTER_CONFIG = 'importer_config'


class ImporterConfigKey(BaseStrEnum):
    """Keys read from the importer configuration payload"""
    TYPE_ID = 'type_id'
