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
Implementation of ImproveObject

Coerces raw imported values (from CSV/JSON) into the types the CMDB expects: booleans for the
``active`` property, ``datetime`` for date-typed fields, and ``str`` for text-typed fields.
"""
import datetime
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.importer.mapper.map_entry import MapEntry
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Mongo extended-JSON key carrying an epoch timestamp in milliseconds (e.g. {'$date': 1700000000000})
MONGO_DATE_KEY: str = '$date'
MILLISECONDS_PER_SECOND: int = 1000

# Recognised string representations for boolean coercion (compared case-insensitively, stripped)
TRUTHY_STRINGS: frozenset[str] = frozenset({'true', '1', 'yes'})
FALSY_STRINGS: frozenset[str] = frozenset({'false', '0', 'no'})

# Date/datetime string formats attempted (in order) when coercing a date-typed field value
DATE_FORMATS: tuple[str, ...] = (
    '%Y/%m/%d', '%Y-%m-%d', '%Y.%m.%d', '%Y,%m,%d',
    '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d,%m,%Y',
    '%d.%m.%y %H:%M', '%d.%m.%y %H:%M:%S', '%y.%m.%d %H:%M', '%y.%m.%d %H:%M:%S',
    '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%Y.%m.%d %H:%M', '%Y.%m.%d %H:%M:%S',
    '%d-%m-%y %H:%M', '%d-%m-%y %H:%M:%S', '%y-%m-%d %H:%M', '%y-%m-%d %H:%M:%S',
    '%d-%m-%Y %H:%M', '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S',
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ImproveObject - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ImproveObject:
    """
    Coerces the raw values of a single imported entry into the types expected by the CMDB
    """

    def __init__(
            self,
            entry: dict,
            property_entries: list[MapEntry],
            field_entries: list[MapEntry],
            possible_fields: list[dict],
        ) -> None:
        """
        Initializes the ImproveObject

        Args:
            entry (dict): The raw imported entry keyed by source column/value identifier
            property_entries (list[MapEntry]): Mappings for object properties (e.g. 'active')
            field_entries (list[MapEntry]): Mappings for object fields
            possible_fields (list[dict]): The target type's field definitions (each with 'name'/'type')
        """
        self.entry = entry
        self.property_entries = property_entries
        self.field_entries = field_entries
        self.possible_fields = possible_fields


    def improve_entry(self) -> dict:
        """
        Converts the entry's property and field values to their appropriate types

        Booleans are coerced for the ``active`` property; date-typed fields are parsed into
        ``datetime`` objects; text-typed fields are stringified when not already strings.

        Returns:
            dict: The same entry, with improved values
        """
        # Improve properties
        for property_entry in self.property_entries:
            if property_entry.get_name() == CmdbObjectKey.ACTIVE.value:
                value = self.entry.get(property_entry.get_value())
                self.entry[property_entry.get_value()] = self.improve_boolean(value)

        # Improve fields
        for entry_field in self.field_entries:
            matching_field = next(
                (field for field in self.possible_fields
                 if field[FieldKey.NAME.value] == entry_field.get_name()),
                None,
            )

            if not matching_field:
                continue

            value = self.entry.get(entry_field.get_value())
            field_type = matching_field[FieldKey.TYPE.value]

            if field_type == FieldType.DATE.value:
                self.entry[entry_field.get_value()] = self.improve_date(value)
            elif field_type == FieldType.TEXT.value and not isinstance(value, str):
                self.entry[entry_field.get_value()] = str(value)

        return self.entry


    @staticmethod
    def improve_boolean(value: Any) -> Any:
        """
        Converts a string representation of a boolean into a boolean

        The comparison is case-insensitive and whitespace-tolerant. Non-string values, and strings
        that match neither set, are returned unchanged.

        Args:
            value (Any): The value to coerce

        Returns:
            Any: True/False for a recognised truthy/falsy string, otherwise the original value
        """
        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in TRUTHY_STRINGS:
                return True
            if normalized in FALSY_STRINGS:
                return False

        return value


    @staticmethod
    def improve_date(value: Any) -> datetime.datetime | Any:
        """
        Converts various date representations into a ``datetime`` object

        Accepts a Mongo extended-JSON dict (``{'$date': <epoch_millis>}``, interpreted as UTC) or a
        string in one of the supported formats. Any unrecognised value is returned unchanged.

        Args:
            value (Any): The date value to convert (a ``{'$date': ...}`` dict or a date string)

        Returns:
            datetime.datetime | Any: The parsed datetime if successful, otherwise the original value
        """
        if isinstance(value, dict):
            timestamp = value.get(MONGO_DATE_KEY)

            if timestamp is not None:
                try:
                    return datetime.datetime.fromtimestamp(
                        timestamp / MILLISECONDS_PER_SECOND,
                        tz=datetime.timezone.utc,
                    )
                except (TypeError, ValueError, OSError) as err:
                    LOGGER.debug("[improve_date] Could not convert %s value %s: %s", MONGO_DATE_KEY, value, err)

        if isinstance(value, str):
            for fmt in DATE_FORMATS:
                try:
                    return datetime.datetime.strptime(value, fmt)
                except ValueError:
                    pass

        return value
