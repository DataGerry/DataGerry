# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.importer.helper.improve_object

DB-free: exercises the value coercion used during CSV/JSON object import. Focus: boolean strings
are normalised symmetrically and case-insensitively, Mongo ``$date`` timestamps are converted as
UTC (including epoch 0), unparseable / unknown values pass through untouched, and ``improve_entry``
coerces only the mapped active property + the date/text fields present on the target type.
"""
import datetime

from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.importer.mapper.map_entry import MapEntry
# -------------------------------------------------------------------------------------------------------------------- #

UTC = datetime.timezone.utc


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  improve_boolean                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImproveBoolean:
    """Coercing string representations of booleans."""

    def test_truthy_strings_return_true(self) -> None:
        """Every recognised truthy spelling (case/whitespace insensitive) becomes True."""
        for raw in ('true', 'TRUE', 'True', '1', 'yes', 'YES', ' Yes '):
            assert ImproveObject.improve_boolean(raw) is True

    def test_falsy_strings_return_false(self) -> None:
        """Every recognised falsy spelling (case/whitespace insensitive) becomes False."""
        for raw in ('false', 'FALSE', 'False', '0', 'no', 'NO', ' no '):
            assert ImproveObject.improve_boolean(raw) is False

    def test_unrecognised_string_is_returned_unchanged(self) -> None:
        """A string that matches neither set is returned verbatim."""
        assert ImproveObject.improve_boolean('maybe') == 'maybe'

    def test_non_string_is_returned_unchanged(self) -> None:
        """Non-string values pass through untouched."""
        assert ImproveObject.improve_boolean(5) == 5
        assert ImproveObject.improve_boolean(None) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    improve_date                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImproveDate:
    """Coercing date values into datetime objects."""

    def test_mongo_date_dict_is_converted_as_utc(self) -> None:
        """A {'$date': millis} dict becomes a UTC-aware datetime at the right instant."""
        result = ImproveObject.improve_date({'$date': 1700000000000})

        assert result == datetime.datetime.fromtimestamp(1700000000000 / 1000, tz=UTC)
        assert result.tzinfo == UTC

    def test_mongo_date_epoch_zero_is_converted(self) -> None:
        """A $date of 0 (epoch) is converted rather than treated as absent (B2)."""
        result = ImproveObject.improve_date({'$date': 0})

        assert result == datetime.datetime(1970, 1, 1, tzinfo=UTC)

    def test_invalid_mongo_date_returns_original_dict(self) -> None:
        """A non-numeric $date is swallowed and the original dict returned (B3)."""
        payload = {'$date': 'not-a-number'}

        assert ImproveObject.improve_date(payload) is payload

    def test_dict_without_date_key_returns_original(self) -> None:
        """A dict lacking the $date key is returned unchanged."""
        payload = {'foo': 'bar'}

        assert ImproveObject.improve_date(payload) is payload

    def test_string_date_formats_are_parsed(self) -> None:
        """Representative supported string formats parse to the same calendar date."""
        expected = datetime.datetime(2024, 1, 15)

        assert ImproveObject.improve_date('2024-01-15') == expected
        assert ImproveObject.improve_date('2024/01/15') == expected
        assert ImproveObject.improve_date('15.01.2024') == expected

    def test_string_datetime_with_time_is_parsed(self) -> None:
        """A format with a time component keeps the time."""
        assert ImproveObject.improve_date('15.01.2024 08:30') == datetime.datetime(2024, 1, 15, 8, 30)

    def test_unparseable_string_is_returned_unchanged(self) -> None:
        """A string matching no format is returned verbatim."""
        assert ImproveObject.improve_date('not a date') == 'not a date'

    def test_non_date_value_is_returned_unchanged(self) -> None:
        """A value that is neither dict nor string passes through."""
        assert ImproveObject.improve_date(42) == 42


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   improve_entry                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImproveEntry:
    """The full CSV-path coercion over an entry's properties and fields."""

    def test_active_property_is_coerced_to_boolean(self) -> None:
        """The mapped 'active' property value is turned into a boolean."""
        entry = {'col_active': 'true'}
        properties = [MapEntry('active', 'col_active')]

        result = ImproveObject(entry, properties, [], []).improve_entry()

        assert result['col_active'] is True

    def test_non_active_property_is_left_untouched(self) -> None:
        """A property other than 'active' is not boolean-coerced."""
        entry = {'col_author': 'true'}
        properties = [MapEntry('author_id', 'col_author')]

        result = ImproveObject(entry, properties, [], []).improve_entry()

        assert result['col_author'] == 'true'

    def test_date_field_is_converted(self) -> None:
        """A field whose target type is 'date' has its value parsed to a datetime."""
        entry = {'col_bd': '2024-01-15'}
        fields = [MapEntry('birthday', 'col_bd')]
        possible = [{'name': 'birthday', 'type': 'date'}]

        result = ImproveObject(entry, [], fields, possible).improve_entry()

        assert result['col_bd'] == datetime.datetime(2024, 1, 15)

    def test_text_field_non_string_is_stringified(self) -> None:
        """A 'text' field carrying a non-string value is coerced to str."""
        entry = {'col_num': 123}
        fields = [MapEntry('label', 'col_num')]
        possible = [{'name': 'label', 'type': 'text'}]

        result = ImproveObject(entry, [], fields, possible).improve_entry()

        assert result['col_num'] == '123'

    def test_text_field_already_string_is_untouched(self) -> None:
        """A 'text' field already holding a string is left as-is."""
        entry = {'col_name': 'alice'}
        fields = [MapEntry('label', 'col_name')]
        possible = [{'name': 'label', 'type': 'text'}]

        result = ImproveObject(entry, [], fields, possible).improve_entry()

        assert result['col_name'] == 'alice'

    def test_field_absent_from_type_is_skipped(self) -> None:
        """A mapped field with no matching type definition is left unchanged."""
        entry = {'col_x': '2024-01-15'}
        fields = [MapEntry('unknown', 'col_x')]
        possible = [{'name': 'other', 'type': 'date'}]

        result = ImproveObject(entry, [], fields, possible).improve_entry()

        assert result['col_x'] == '2024-01-15'

    def test_returns_the_same_entry_instance(self) -> None:
        """improve_entry mutates and returns the same dict it was given."""
        entry = {'col_active': 'no'}
        improver = ImproveObject(entry, [MapEntry('active', 'col_active')], [], [])

        result = improver.improve_entry()

        assert result is entry
        assert result['col_active'] is False
