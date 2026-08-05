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
from logging import Logger, getLogger

from cmdb.framework.importer.content_types import JSONContent
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           JsonObjectImporterConfig - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonObjectImporterConfig(ObjectImporterConfig, JSONContent):
    """
    Importer configuration for JSON files

    Extends: ObjectImporterConfig, JSONContent
    """

    DEFAULT_MAPPING = {
        'properties': {
            'public_id': 'public_id',
            'active': 'active',
        },
        'fields': {
        }
    }

    MANUALLY_MAPPING = False

    def __init__(self,
                 type_id: int,
                 mapping: Mapping | None = None,
                 start_element: int = 0,
                 max_elements: int = 0,
                 overwrite_public: bool = True,
                 *args,
                 **kwargs):
        super().__init__(
            type_id=type_id,
            mapping=mapping,
            start_element=start_element,
            max_elements=max_elements,
            overwrite_public=overwrite_public
        )
