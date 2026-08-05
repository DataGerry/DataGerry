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
Implementation of helper functions for the importer workflows
"""
from typing import Any

from cmdb.framework.importer.parser.csv_object_parser import CsvObjectParser
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.importers.csv_object_importer import CsvObjectImporter
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.importers.json_object_importer import JsonObjectImporter
from cmdb.framework.importer.configs.json_object_importer_config import JsonObjectImporterConfig

from cmdb.errors.importer import ImporterLoadError, ParserLoadError
# -------------------------------------------------------------------------------------------------------------------- #

__OBJECT_IMPORTER__: dict[str, Any] = {
    'json': JsonObjectImporter,
    'csv': CsvObjectImporter
}

__OBJECT_IMPORTER_CONFIG__: dict[str, Any] = {
    'json': JsonObjectImporterConfig,
    'csv': CsvObjectImporterConfig
}

__OBJECT_PARSER__: dict[str, Any] = {
    'json': JsonObjectParser,
    'csv': CsvObjectParser
}


def load_importer_class(importer_type: str, importer_name: str) -> JsonObjectImporter | CsvObjectImporter:
    """
    Loads the importer class based on the provided importer type and name
    
    Args:
        importer_type (str): The type of the importer (e.g., 'object')
        importer_name (str): The name of the specific importer class to load
        
    Returns:
        'JsonObjectImporter' | 'CsvObjectImporter': The corresponding importer class
        
    Raises:
        ImporterLoadError: If the importer type or name is invalid, or the importer class cannot be found
    """
    # Define a mapping of importer types to configuration objects
    importer_config_mapping: dict[str, dict[str, Any]] = {
        'object': __OBJECT_IMPORTER__
    }

    # Check if the importer type is valid
    if importer_type not in importer_config_mapping:
        raise ImporterLoadError(f"Invalid importer type: {importer_type}")

    # Retrieve the importer configuration for the given type
    importer_config: dict[str, Any] = importer_config_mapping[importer_type]

    # Check if the importer name exists in the configuration
    if importer_name not in importer_config:
        raise ImporterLoadError(f"Invalid importer name: {importer_name} for type {importer_type}")

    # Retrieve the importer class
    importer_class: Any = importer_config[importer_name]

    # Ensure the importer class is valid
    if not importer_class:
        raise ImporterLoadError(f"[{importer_type} - {importer_name}]: No importer class found!")

    return importer_class


def load_importer_config_class(
        importer_type: str,
        importer_name: str
    ) -> JsonObjectImporterConfig | CsvObjectImporterConfig:
    """
    Loads the importer configuration class based on the provided importer type and name
    
    Args:
        importer_type (str): The type of the importer (e.g., 'object')
        importer_name (str): The name of the specific importer configuration to load
        
    Returns:
        'JsonObjectImporterConfig' | 'CsvObjectImporterConfig': The corresponding importer configuration class
        
    Raises:
        ImporterLoadError: If the importer type or name is invalid, or the importer configuration cannot be found
    """
    importer_config_mapping = {
        'object': __OBJECT_IMPORTER_CONFIG__
    }

    # Retrieve the importer configuration for the given type
    importer_config = importer_config_mapping[importer_type]

    # Check if the importer name exists in the configuration
    if importer_name not in importer_config:
        raise ImporterLoadError(f"Invalid importer name: {importer_name} for type {importer_type}")

    # Retrieve the importer configuration class
    importer_config_class = importer_config[importer_name]

    # Ensure the configuration class is valid
    if not importer_config_class:
        raise ImporterLoadError(f"[{importer_type} - {importer_name}]: No importer_config_class found!")

    return importer_config_class


def load_parser_class(parser_type: str, parser_name: str) -> JsonObjectParser | CsvObjectParser:
    """
    Loads the parser class based on the provided parser type and name
    
    Args:
        parser_type (str): The type of the parser (e.g., 'object')
        parser_name (str): The name of the specific parser class to load
        
    Returns:
        'JsonObjectParser' | 'CsvObjectParser': The corresponding parser class
        
    Raises:
        ParserLoadError: If the parser type or name is invalid, or the parser class cannot be found
    """
    # Define a mapping of parser types to configuration objects
    parser_config_mapping = {
        'object': __OBJECT_PARSER__
    }

    # Check if the parser type is valid
    if parser_type not in parser_config_mapping:
        raise ParserLoadError(f"Invalid parser type: {parser_type}")

    # Retrieve the parser configuration for the given type
    parser_config = parser_config_mapping[parser_type]

    # Check if the parser name exists in the configuration
    if parser_name not in parser_config:
        raise ParserLoadError(f"Invalid parser name: {parser_name} for type {parser_type}")

    # Retrieve the parser class
    parser_class = parser_config[parser_name]

    # Ensure the parser class is valid
    if not parser_class:
        raise ParserLoadError(f"[{parser_type} - {parser_name}]: No parser class found!")

    return parser_class
