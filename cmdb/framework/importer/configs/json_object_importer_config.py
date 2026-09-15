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
Implementation of JsonObjectImporterConfig
"""
from cmdb.framework.importer.content_types import JSONContent
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.importer_constants import JsonMappingKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                           JsonObjectImporterConfig - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonObjectImporterConfig(ObjectImporterConfig, JSONContent):
    """
    Importer configuration for JSON files

    JSON imports use a fixed mapping (``MANUALLY_MAPPING = False``), so ``DEFAULT_MAPPING`` is a
    plain dict describing the property/field mapping consumed by the JSON importer, and no mapping is
    supplied by the client. The constructor is inherited from ObjectImporterConfig.

    Extends: ObjectImporterConfig, JSONContent
    """

    DEFAULT_MAPPING = {
        JsonMappingKey.PROPERTIES.value: {
            CmdbObjectKey.PUBLIC_ID.value: CmdbObjectKey.PUBLIC_ID.value,
            CmdbObjectKey.ACTIVE.value: CmdbObjectKey.ACTIVE.value,
        },
        JsonMappingKey.FIELDS.value: {}
    }

    MANUALLY_MAPPING = False
