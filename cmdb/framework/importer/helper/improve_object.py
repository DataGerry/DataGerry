# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of ImproveObject
"""
import logging
import datetime
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ImproveObject - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ImproveObject:
    """
    Base class for improving object imports by converting field values to appropriate types
    """

    def __init__(self, entry: dict, property_entries: list, field_entries: list, possible_fields: list):
        """
        Initializes the ImproveObject

        Args:
            entry (dict): Dictionary containing field values
            property_entries (list): Object properties
            field_entries (list): Field attributes
            possible_fields (list): List of field types and their mappings
        """
        self.entry = entry
        self.property_entries = property_entries
        self.field_entries = field_entries
        self.possible_fields = possible_fields
        self.value = None


    def improve_entry(self) -> dict:
        """
        Converts field values to their appropriate types

        Returns:
            dict: The updated entry with improved values
        """
        # improve properties
        for property_entry in self.property_entries:
            self.value = self.entry.get(property_entry.get_value())
            if property_entry.get_name() == "active":
                self.entry[property_entry.get_value()] = self.improve_boolean(self.value)

        # improve fields
        for entry_field in self.field_entries:
            self.value = self.entry.get(entry_field.get_value())
            matching_field = next((item for item in self.possible_fields if
                                   item["name"] == entry_field.get_name()), None)

            if matching_field:
                if matching_field['type'] == 'date':
                    self.entry[entry_field.get_value()] = self.improve_date(self.value)
                elif matching_field['type'] == 'text' and not isinstance(self.value, str):
                    self.entry[entry_field.get_value()] = str(self.value)

        return self.entry


    @staticmethod
    def improve_boolean(value: Any) -> bool | Any:
        """
        Converts a string representation of a boolean into a boolean type.

        Args:
            value (str): The value to be converted.

        Returns:
            bool: True if the value represents a truthy string, False otherwise.
        """
        truthy_values: set[str] = {'True', 'true', 'TRUE', '1'}
        falsy_values: set[str] = {'False', 'false', 'FALSE', '0', 'no'}

        if isinstance(value, str):
            if value in falsy_values:
                return False
            if value in truthy_values:
                return True

        return value


    @staticmethod
    def improve_date(value: str | dict) -> datetime.datetime | str | dict:
        """
        Converts various date formats into a standardized datetime object.

        Args:
            value (str | dict): The date value to be converted.
                                      It can be a string or a dictionary containing a timestamp

        Returns:
            datetime.datetime | str | dict: Parsed datetime object if successful,
                                                 otherwise returns the original value.
        """
        try:
            if isinstance(value, dict) and value.get('$date'):
                return datetime.datetime.fromtimestamp(value["$date"] / 1000)
        except Exception:
            pass

        if isinstance(value, str):
            dt_formats = (
                '%Y/%m/%d', '%Y-%m-%d', '%Y.%m.%d', '%Y,%m,%d',
                '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d,%m,%Y',
                '%d.%m.%y %H:%M', '%d.%m.%y %H:%M:%S', '%y.%m.%d %H:%M', '%y.%m.%d %H:%M:%S',
                '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%Y.%m.%d %H:%M', '%Y.%m.%d %H:%M:%S',
                '%d-%m-%y %H:%M', '%d-%m-%y %H:%M:%S', '%y-%m-%d %H:%M', '%y-%m-%d %H:%M:%S',
                '%d-%m-%Y %H:%M', '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'
            )

            for fmt in dt_formats:
                try:
                    return datetime.datetime.strptime(value, fmt)
                except ValueError:
                    pass

        return value
