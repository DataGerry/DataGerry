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
Unit tests for cmdb.interface.rest_api.routes.routes_helper

The shared multipart-request helpers (get_file_in_request / get_element_from_data_request, consolidated
here from the importer + media-library route utils) plus fetch_only_active_objects and the two public_id
readers (extract_public_ids for a URL segment, normalize_public_id_list for a JSON body), exercised
inside a minimal Flask request context (no REST API booted).
"""
import json
from io import BytesIO

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from typing import Any

from cmdb.interface.rest_api.routes.routes_helper import (
    get_file_in_request,
    get_element_from_data_request,
    fetch_only_active_objects,
    extract_public_ids,
    normalize_public_id_list,
)
# -------------------------------------------------------------------------------------------------------------------- #

app = Flask(__name__)


class TestGetFileInRequest:
    """get_file_in_request returns the uploaded file or aborts 400 when it is missing."""

    def test_returns_file_when_present(self) -> None:
        """The uploaded file is returned when the named field is present."""
        with app.test_request_context(
            '/', method='POST',
            data={'file': (BytesIO(b'content'), 'import.csv')},
            content_type='multipart/form-data',
        ):
            assert get_file_in_request('file').filename == 'import.csv'

    def test_missing_file_aborts_400(self) -> None:
        """A missing file field aborts with 400."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc:
                get_file_in_request('file')

            assert exc.value.code == 400


class TestGetElementFromDataRequest:
    """get_element_from_data_request parses a JSON form field, or returns None on miss / bad JSON."""

    def test_parses_json_field(self) -> None:
        """A valid JSON form field is parsed into a Python object."""
        with app.test_request_context(
            '/', method='POST',
            data={'cfg': json.dumps({'a': 1})},
            content_type='multipart/form-data',
        ):
            assert get_element_from_data_request('cfg', request) == {'a': 1}

    def test_missing_field_returns_none(self) -> None:
        """A missing form field returns None."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            assert get_element_from_data_request('cfg', request) is None

    def test_invalid_json_returns_none(self) -> None:
        """A form field that is not valid JSON returns None."""
        with app.test_request_context(
            '/', method='POST',
            data={'cfg': 'not-json'},
            content_type='multipart/form-data',
        ):
            assert get_element_from_data_request('cfg', request) is None


class TestFetchOnlyActiveObjects:
    """fetch_only_active_objects reads the onlyActiveObjCookie query flag as a bool."""

    @pytest.mark.parametrize('value, expected', [('true', True), ('True', True), ('false', False)])
    def test_reads_cookie_flag(self, value: str, expected: bool) -> None:
        """The flag is True only for 'true'/'True'."""
        with app.test_request_context(f'/?onlyActiveObjCookie={value}'):
            assert fetch_only_active_objects() is expected

    def test_absent_flag_is_false(self) -> None:
        """A missing flag defaults to False."""
        with app.test_request_context('/'):
            assert fetch_only_active_objects() is False


class TestExtractPublicIds:
    """extract_public_ids parses a comma-separated id list, aborting 400 on a non-integer."""

    def test_parses_comma_separated_ids(self) -> None:
        """A well-formed list is parsed into ints."""
        with app.test_request_context('/'):
            assert extract_public_ids('1,2,3') == [1, 2, 3]

    def test_non_integer_aborts_400(self) -> None:
        """A non-integer token aborts with 400."""
        with app.test_request_context('/'):
            with pytest.raises(HTTPException) as exc:
                extract_public_ids('1,x,3')

            assert exc.value.code == 400

    def test_duplicates_and_order_are_preserved(self) -> None:
        """The caller decides what a repeated id means, so the parser keeps the list as given."""
        with app.test_request_context('/'):
            assert extract_public_ids('3,1,3') == [3, 1, 3]

    @pytest.mark.parametrize(
        'segment',
        [' 1 ', '1, 2', '+1', '1_0', '\u0665', '1.0', '0', '-1', '', '1,', ',1', '1,,2'],
        ids=['padded', 'padded-second', 'plus', 'underscore', 'arabic-indic', 'float',
             'zero', 'negative', 'empty', 'trailing-comma', 'leading-comma', 'empty-in-the-middle'],
    )
    def test_only_plain_positive_numbers_are_accepted(self, segment: str) -> None:
        """`int()` alone would read several of these as ids the caller never wrote."""
        with app.test_request_context('/'):
            with pytest.raises(HTTPException) as exc:
                extract_public_ids(segment)

            assert exc.value.code == 400

    def test_the_offending_value_is_named(self) -> None:
        """The message points at the value that failed, not just at the segment."""
        with app.test_request_context('/'):
            with pytest.raises(HTTPException) as exc:
                extract_public_ids('1,5_3,3')

            assert '5_3' in exc.value.description


class TestNormalizePublicIdList:
    """normalize_public_id_list reads a JSON body selection as plain positive integers."""

    def test_accepts_numbers_and_digit_strings(self) -> None:
        """Both JSON forms of an id end up as the same integer, order preserved."""
        assert normalize_public_id_list([3, '1', 2]) == [3, 1, 2]

    def test_keeps_duplicates(self) -> None:
        """Duplicates are the caller's business, not the reader's."""
        assert normalize_public_id_list([4, 4]) == [4, 4]

    def test_accepts_an_empty_selection(self) -> None:
        """An empty list normalises to an empty list (the caller decides whether that is an error)."""
        assert normalize_public_id_list([]) == []

    @pytest.mark.parametrize(
        'value',
        [True, False],
        ids=['true', 'false'],
    )
    def test_rejects_booleans(self, value: Any) -> None:
        """A JSON boolean is an int in Python - accepting it would address public_id 1 (regression)."""
        with pytest.raises(HTTPException) as exc_info:
            normalize_public_id_list([value])

        assert exc_info.value.code == 400

    @pytest.mark.parametrize(
        'value',
        [0, -1, '0', '-5'],
        ids=['zero', 'negative', 'zero-string', 'negative-string'],
    )
    def test_rejects_non_positive_ids(self, value: Any) -> None:
        """public_ids start at 1, so 0 and negatives are refused."""
        with pytest.raises(HTTPException) as exc_info:
            normalize_public_id_list([value])

        assert exc_info.value.code == 400

    @pytest.mark.parametrize(
        'value',
        [None, 1.5, '1.5', ' 7', '7_0', '٥', 'abc', [1], {'id': 1}],
        ids=['none', 'float', 'float-string', 'padded', 'underscored', 'non-ascii-digit',
             'text', 'list', 'dict'],
    )
    def test_rejects_anything_else(self, value: Any) -> None:
        """Everything int() would silently coerce (or choke on) is refused up front."""
        with pytest.raises(HTTPException) as exc_info:
            normalize_public_id_list([value])

        assert exc_info.value.code == 400

    def test_reports_the_offending_value(self) -> None:
        """The 400 names the value that was refused, so the caller can find it in its payload."""
        with pytest.raises(HTTPException) as exc_info:
            normalize_public_id_list([1, 'nope'])

        assert 'nope' in exc_info.value.description
