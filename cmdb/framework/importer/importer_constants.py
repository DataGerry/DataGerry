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
Shared constants for the object importer framework engine
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The only importer/parser kind resolved by the registry today (object imports)
IMPORTER_KIND_OBJECT: str = 'object'

# Version stamped onto every freshly generated imported object
DEFAULT_OBJECT_VERSION: str = '1.0.0'


class JsonMappingKey(BaseStrEnum):
    """Top-level keys of the JSON importer's fixed mapping (``JsonObjectImporterConfig.DEFAULT_MAPPING``)"""
    PROPERTIES = 'properties'
    FIELDS = 'fields'


class MapEntryOptionKey(BaseStrEnum):
    """Option keys carried by a mapping ``MapEntry`` (CSV import)"""
    TYPE = 'type'
    REF_NAME = 'ref_name'
    TYPE_ID = 'type_id'


class MapEntryType(BaseStrEnum):
    """The ``type`` option of a mapping ``MapEntry`` — how a source column maps onto the object"""
    PROPERTY = 'property'
    FIELD = 'field'
    REFERENCE = 'ref'


class ImporterFileFormat(BaseStrEnum):
    """
    Supported import file formats used as registry keys

    The values intentionally match the ``FILE_TYPE`` of the corresponding content-type mixins
    (``JSONContent.FILE_TYPE`` / ``CSVContent.FILE_TYPE``), so a raw ``file_format`` request value
    resolves directly against the registries.
    """
    JSON = 'json'
    CSV = 'csv'


class JsonParserConfigKey(BaseStrEnum):
    """Keys of the JSON parser configuration (also the FE-facing default-config payload)"""
    INDENT = 'indent'
    ENCODING = 'encoding'


class CsvParserConfigKey(BaseStrEnum):
    """Keys of the CSV parser configuration (also the FE-facing default-config payload)"""
    DELIMITER = 'delimiter'
    NEWLINE = 'newline'
    QUOTE_CHAR = 'quoteChar'
    ESCAPE_CHAR = 'escapeChar'
    HEADER = 'header'
    ENCODING = 'encoding'
