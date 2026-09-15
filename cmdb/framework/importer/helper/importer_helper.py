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
Registries and lookup helpers that resolve the importer, importer-config and parser classes
for a given import kind (e.g. ``object``) and file format (e.g. ``json`` / ``csv``)
"""
from typing import Any

from cmdb.framework.importer.importer_constants import IMPORTER_KIND_OBJECT, ImporterFileFormat
from cmdb.framework.importer.parser.csv_object_parser import CsvObjectParser
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.importers.csv_object_importer import CsvObjectImporter
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.importers.json_object_importer import JsonObjectImporter
from cmdb.framework.importer.configs.json_object_importer_config import JsonObjectImporterConfig

from cmdb.errors.importer import ImporterError, ImporterLoadError, ParserLoadError
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_IMPORTER_REGISTRY: dict[str, Any] = {
    ImporterFileFormat.JSON: JsonObjectImporter,
    ImporterFileFormat.CSV: CsvObjectImporter,
}

OBJECT_IMPORTER_CONFIG_REGISTRY: dict[str, Any] = {
    ImporterFileFormat.JSON: JsonObjectImporterConfig,
    ImporterFileFormat.CSV: CsvObjectImporterConfig,
}

OBJECT_PARSER_REGISTRY: dict[str, Any] = {
    ImporterFileFormat.JSON: JsonObjectParser,
    ImporterFileFormat.CSV: CsvObjectParser,
}


def _resolve_registered_class(
        kind: str,
        name: str,
        registries: dict[str, dict[str, Any]],
        error_cls: type[ImporterError],
        label: str,
    ) -> Any:
    """
    Resolve a registered class from a per-kind registry, raising a consistent error on any miss

    Args:
        kind (str): The import kind selecting the registry (e.g. 'object')
        name (str): The file format selecting the class within the registry (e.g. 'json' / 'csv')
        registries (dict[str, dict[str, Any]]): Mapping of kind to its {format: class} registry
        error_cls (type[ImporterError]): The error class to raise when resolution fails
        label (str): Human-readable label used in the raised error messages (e.g. 'importer')

    Returns:
        Any: The resolved class (not an instance)

    Raises:
        ImporterError: (as ``error_cls``) if the kind or name is unknown, or the entry is falsy
    """
    if kind not in registries:
        raise error_cls(f"Invalid {label} type: {kind}")

    registry: dict[str, Any] = registries[kind]

    if name not in registry:
        raise error_cls(f"Invalid {label} name: {name} for type {kind}")

    resolved: Any = registry[name]

    if not resolved:
        raise error_cls(f"[{kind} - {name}]: No {label} class found!")

    return resolved


def load_importer_class(importer_type: str, importer_name: str) -> type[JsonObjectImporter | CsvObjectImporter]:
    """
    Load the importer class for the given import kind and file format

    Args:
        importer_type (str): The import kind (e.g. 'object')
        importer_name (str): The file format of the importer to load (e.g. 'json' / 'csv')

    Returns:
        type[JsonObjectImporter | CsvObjectImporter]: The corresponding importer class

    Raises:
        ImporterLoadError: If the import kind or file format is unknown, or no class is registered
    """
    return _resolve_registered_class(
        importer_type,
        importer_name,
        {IMPORTER_KIND_OBJECT: OBJECT_IMPORTER_REGISTRY},
        ImporterLoadError,
        'importer',
    )


def load_importer_config_class(
        importer_type: str,
        importer_name: str,
    ) -> type[JsonObjectImporterConfig | CsvObjectImporterConfig]:
    """
    Load the importer configuration class for the given import kind and file format

    Args:
        importer_type (str): The import kind (e.g. 'object')
        importer_name (str): The file format of the importer config to load (e.g. 'json' / 'csv')

    Returns:
        type[JsonObjectImporterConfig | CsvObjectImporterConfig]: The corresponding importer config class

    Raises:
        ImporterLoadError: If the import kind or file format is unknown, or no class is registered
    """
    return _resolve_registered_class(
        importer_type,
        importer_name,
        {IMPORTER_KIND_OBJECT: OBJECT_IMPORTER_CONFIG_REGISTRY},
        ImporterLoadError,
        'importer config',
    )


def load_parser_class(parser_type: str, parser_name: str) -> type[JsonObjectParser | CsvObjectParser]:
    """
    Load the parser class for the given parser kind and file format

    Args:
        parser_type (str): The parser kind (e.g. 'object')
        parser_name (str): The file format of the parser to load (e.g. 'json' / 'csv')

    Returns:
        type[JsonObjectParser | CsvObjectParser]: The corresponding parser class

    Raises:
        ParserLoadError: If the parser kind or file format is unknown, or no class is registered
    """
    return _resolve_registered_class(
        parser_type,
        parser_name,
        {IMPORTER_KIND_OBJECT: OBJECT_PARSER_REGISTRY},
        ParserLoadError,
        'parser',
    )
