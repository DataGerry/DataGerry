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
Constants of the catalog routes of the IsmsControlMeasures: the import request, its answer and the write schemas
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model import IsmsControlMeasure
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.class_schema.write_schema_helper import build_write_schema
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CatalogImportKey',
    'CatalogImportResultKey',
    'CATALOG_IMPORT_SCHEMA',
    'CONTROL_MEASURE_WRITE_SCHEMA',
    'CATALOG_IMPORT_FAILED_MESSAGE',
    'CATALOG_STATUS_FAILED_MESSAGE',
    'CATALOG_DELETE_FAILED_MESSAGE',
    'CATALOG_OPTIONS_FAILED_MESSAGE',
    'CATALOG_READ_FAILED_MESSAGE',
    'CATALOG_WRITE_FAILED_MESSAGE',
]


class CatalogImportKey(BaseStrEnum):
    """
    The keys of a catalog import request beside the control keys (``ControlMeasureKey``)
    """
    CATALOG_TITLE = 'catalog_title'
    CONTROLS = 'controls'


class CatalogImportResultKey(BaseStrEnum):
    """
    The keys of a catalog import answer
    """
    IMPORTED = 'imported'
    UPDATED = 'updated'
    UNCHANGED = 'unchanged'
    OBSOLETE = 'obsolete'


# The body of POST /isms/control_measures/catalog_import: the catalog and its requirements, flattened by the client
CATALOG_IMPORT_SCHEMA: dict[str, Any] = {
    ControlMeasureKey.CATALOG_ID.value: {'type': 'string', 'required': True, 'empty': False},
    CatalogImportKey.CATALOG_TITLE.value: {'type': 'string', 'required': True, 'empty': False},
    CatalogImportKey.CONTROLS.value: {
        'type': 'list',
        'required': True,
        'schema': {
            'type': 'dict',
            'schema': {
                ControlMeasureKey.IDENTIFIER.value: {'type': 'string', 'required': True, 'empty': False},
                ControlMeasureKey.TITLE.value: {'type': 'string', 'required': True, 'empty': False},
                ControlMeasureKey.CHAPTER.value: {'type': 'string', 'nullable': True},
                ControlMeasureKey.DESCRIPTION.value: {'type': 'string', 'nullable': True},
            },
        },
    },
}

# The body of a ControlMeasure create / update: the identity and the catalog are the server's - only the catalog
# import sets ``catalog_id``, so a client cannot tag a control as part of a catalog (whose re-import would then
# rewrite it and whose delete would remove it)
CONTROL_MEASURE_WRITE_SCHEMA: dict[str, Any] = build_write_schema(
    IsmsControlMeasure.SCHEMA, server_owned=(CmdbDAO.PUBLIC_ID_KEY, ControlMeasureKey.CATALOG_ID.value),
)

CATALOG_IMPORT_FAILED_MESSAGE: str = "while importing the requirements of a catalog as ControlMeasures"
CATALOG_STATUS_FAILED_MESSAGE: str = "while counting the imported catalog controls"
CATALOG_DELETE_FAILED_MESSAGE: str = "while deleting the controls of the catalog: {catalog_id}"

# Refusals (HTTP 400) of a catalog import whose reads or writes failed. Nothing is formatted into them: the route has
# no public_id, so the per-id ISMS templates would show their placeholder
CATALOG_OPTIONS_FAILED_MESSAGE: str = (
    "Failed to read or create the catalog's source and implementation state options!"
)
CATALOG_READ_FAILED_MESSAGE: str = "Failed to read the ControlMeasures of the catalog from the database!"
CATALOG_WRITE_FAILED_MESSAGE: str = (
    "Failed to write the ControlMeasures of the catalog - import the catalog again to finish!"
)
