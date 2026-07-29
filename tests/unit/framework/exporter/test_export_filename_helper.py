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
Unit tests for cmdb.framework.exporter.export_filename_helper

Pins the exported-file naming both export paths share: the timestamp (EXPORT_FILENAME_TIMESTAMP_FMT,
taken in UTC rather than in the server's local timezone) and the parts that follow it -
`<timestamp>_<kind>_<subject>[_readable].<extension>`. The subject rules and the sanitising are the
interesting part: a CmdbType name is free text that ends up both on a filesystem and in a
Content-Disposition header.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from cmdb.framework.exporter.exporter_constants import (
    EXPORT_FILENAME_TIMESTAMP_FMT,
    EXPORT_FILENAME_SUBJECT_MAX_LENGTH,
    EXPORT_FILENAME_MAX_LENGTH,
)
from cmdb.framework.exporter.export_filename_helper import (
    build_export_filename_timestamp,
    build_export_filename,
    build_object_export_filename,
    build_object_export_subject,
    build_type_export_filename,
    sanitize_filename_part,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Slack allowed between the stamp and the assertion clock, so the test cannot fail on a slow machine
MAX_CLOCK_SKEW: timedelta = timedelta(minutes=5)


def test_timestamp_matches_the_export_filename_format() -> None:
    """The stamp is parseable with the shared strftime format (so it is filename-safe and stable)."""
    stamp = build_export_filename_timestamp()

    assert datetime.strptime(stamp, EXPORT_FILENAME_TIMESTAMP_FMT)


def test_timestamp_is_taken_in_utc() -> None:
    """The stamp tracks UTC rather than the server's local timezone."""
    stamp = build_export_filename_timestamp()

    parsed = datetime.strptime(stamp, EXPORT_FILENAME_TIMESTAMP_FMT).replace(tzinfo=timezone.utc)

    assert abs(parsed - datetime.now(timezone.utc)) < MAX_CLOCK_SKEW


# The leading timestamp of every export filename
TIMESTAMP_PREFIX: str = r'\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}'


class TestSanitizeFilenamePart:
    """A filename part is reduced to a lower-case, ASCII, separator-safe token."""

    @pytest.mark.parametrize(
        'raw, expected',
        [
            ('router', 'router'),
            ('Router', 'router'),
            ('Router Device', 'router-device'),
            ('router/device', 'router-device'),
            ('router:*?device', 'router-device'),
            ('routür', 'rout-r'),
            ('  router  ', 'router'),
            ('---router---', 'router'),
            ('router...', 'router'),
            ('a  b   c', 'a-b-c'),
        ],
        ids=['plain', 'upper', 'space', 'slash', 'windows-reserved', 'umlaut', 'padded',
             'separator-padded', 'trailing-dots', 'collapsed'],
    )
    def test_reduces_to_a_safe_token(self, raw: str, expected: str) -> None:
        """Everything outside the allowed set collapses into one replacement character."""
        assert sanitize_filename_part(raw) == expected

    @pytest.mark.parametrize(
        'raw',
        ['', '   ', '///', '***', None],
        ids=['empty', 'blank', 'slashes', 'stars', 'none'],
    )
    def test_unusable_values_yield_an_empty_token(self, raw: str) -> None:
        """A value with nothing usable left is empty, which the callers treat as 'no subject'."""
        assert sanitize_filename_part(raw) == ''

    def test_a_line_break_can_not_reach_the_header(self) -> None:
        """A CRLF in a type name must not survive into a Content-Disposition value."""
        sanitized = sanitize_filename_part('router\r\nX-Injected: 1')

        assert '\r' not in sanitized
        assert '\n' not in sanitized

    def test_the_token_is_length_capped(self) -> None:
        """A very long type name cannot blow the filename up."""
        assert len(sanitize_filename_part('a' * 200)) == EXPORT_FILENAME_SUBJECT_MAX_LENGTH


class TestObjectExportSubject:
    """The subject names WHAT an object export contains."""

    def test_one_type_is_named_after_it(self) -> None:
        """The common case: a single type's export carries its name."""
        assert build_object_export_subject(['router']) == 'router'

    def test_several_types_are_named_by_count(self) -> None:
        """A multi-type selection (JSON / XML / ZIP) is counted rather than listed."""
        assert build_object_export_subject(['router', 'switch', 'firewall']) == '3-types'

    def test_no_objects_is_named_explicitly(self) -> None:
        """A filter that matched nothing has no type to name."""
        assert build_object_export_subject([]) == 'no-objects'

    def test_an_unusable_type_name_falls_back_to_the_count(self) -> None:
        """A name made only of replaced characters would leave nothing to identify the type by."""
        assert build_object_export_subject(['***']) == '1-types'


class TestBuildObjectExportFilename:
    """The object export filename."""

    def test_names_the_kind_and_the_type(self) -> None:
        """`<timestamp>_objects_<type>.<ext>`."""
        filename = build_object_export_filename(['router'], 'csv')

        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_objects_router\\.csv', filename)

    def test_marks_a_human_readable_export(self) -> None:
        """A presentation export is not re-importable, so the name says so."""
        filename = build_object_export_filename(['router'], 'csv', human_readable=True)

        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_objects_router_readable\\.csv', filename)

    def test_a_plain_export_carries_no_readable_marker(self) -> None:
        """The marker only appears for a human-readable export."""
        assert 'readable' not in build_object_export_filename(['router'], 'csv')

    def test_multi_type_and_empty_exports_are_named(self) -> None:
        """The two non-single-type cases keep the same shape."""
        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_objects_2-types\\.json',
                            build_object_export_filename(['router', 'switch'], 'json'))
        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_objects_no-objects\\.json',
                            build_object_export_filename([], 'json'))

    def test_a_hostile_type_name_is_sanitised(self) -> None:
        """The type name reaches both a filesystem and a header, so it is reduced to safe characters."""
        filename = build_object_export_filename(['Router "Edge"/Prod'], 'csv')

        assert '"' not in filename
        assert '/' not in filename
        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_objects_router-edge-prod\\.csv', filename)


class TestBuildTypeExportFilename:
    """The CmdbType export filename."""

    @pytest.mark.parametrize('count', [0, 1, 47], ids=['none', 'one', 'many'])
    def test_names_the_kind_and_the_count(self, count: int) -> None:
        """A type export is a catalogue slice, so its SIZE is the useful subject."""
        filename = build_type_export_filename(count, 'json')

        assert re.fullmatch(f'{TIMESTAMP_PREFIX}_types_{count}\\.json', filename)


class TestBuildExportFilename:
    """The shared assembly."""

    def test_the_timestamp_leads_so_names_sort_chronologically(self) -> None:
        """The date is the first thing in the name, which is the point of the layout."""
        filename = build_export_filename('objects', 'router', 'csv')

        assert datetime.strptime(filename.split('_objects_')[0], EXPORT_FILENAME_TIMESTAMP_FMT)

    def test_the_assembled_name_is_length_capped(self) -> None:
        """Even a pathological subject cannot produce an unusable filename."""
        filename = build_export_filename('objects', 'x' * 300, 'csv')

        assert len(filename) <= EXPORT_FILENAME_MAX_LENGTH + len('.csv')

    def test_an_empty_subject_leaves_no_double_separator(self) -> None:
        """An empty part is dropped rather than producing '__' in the middle of the name."""
        assert '__' not in build_export_filename('objects', '', 'csv')
