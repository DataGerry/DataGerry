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

# Reported for an object whose import failed with an error the import itself did not anticipate. The
# batch keeps running and the object lands in failed_imports like any other rejection, so a defect in
# one object's data can never discard the objects around it
UNEXPECTED_OBJECT_IMPORT_ERROR: str = 'Unexpected error while importing this object: {detail}'


class JsonMappingKey(BaseStrEnum):
    """Top-level keys of the JSON importer's fixed mapping (``JsonObjectImporterConfig.DEFAULT_MAPPING``)"""
    PROPERTIES = 'properties'
    FIELDS = 'fields'


# Human-readable summary line of a bulk import (``ImportReportResponse.message``). Both counts are
# always present - including the zeroes - so the outcome of any batch can be read off one line without
# comparing it against the request. It is a log / API-consumer convenience only: the frontend renders
# its own counts from success_imports and failed_imports, so this string is never parsed. A partially
# or fully failed import is still HTTP 200
IMPORT_SUMMARY_MESSAGE: str = 'Imported {success} of {total} {noun}, {failed} failed'


class ImportNoun(BaseStrEnum):
    """What a bulk import counted, named in its summary line (``IMPORT_SUMMARY_MESSAGE``)"""
    OBJECT = 'object'
    TYPE = 'type'


# Appended to an ``ImportNoun`` when the summary line counts anything other than exactly one element
IMPORT_NOUN_PLURAL_SUFFIX: str = 's'


class MapEntryOptionKey(BaseStrEnum):
    """
    Option keys the import reads off a mapping ``MapEntry`` (CSV import)

    A ``MapEntry`` keeps every option it is handed, so a payload may carry more keys than these - they
    are simply never read. ``ref_name`` is one such key: it belonged to the retired CSV reference
    lookup (references are cleared on import now, see ``csv_object_importer._build_object_fields``)
    """
    TYPE = 'type'
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
    ENCODING = 'encoding'


class CsvParserConfigKey(BaseStrEnum):
    """Keys of the CSV parser configuration (also the FE-facing default-config payload)"""
    DELIMITER = 'delimiter'
    NEWLINE = 'newline'
    QUOTE_CHAR = 'quoteChar'
    ESCAPE_CHAR = 'escapeChar'
    HEADER = 'header'
    ENCODING = 'encoding'
