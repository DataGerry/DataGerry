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
Unit tests for the DocapiTemplate list helpers

Pure: no Mongo; a plain Flask app only for the request the readers look at. Pinned: ``type_id`` is a positive
integer or a 400 (never a silently dropped filter), ``active`` follows the API's one flag rule and is None when
absent, and the condition names the type by the dotted ``template_parameters.type`` path - with only the keys a
parameter was given for. "Active" is what the model reads as active: ``true``, ``null`` or no key at all.
"""
from typing import Any
from urllib.parse import unquote

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    TYPE_ID_INVALID_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_helper import (
    TEMPLATE_TYPE_PATH,
    build_template_list_condition,
    read_template_active_param,
    read_template_type_id_param,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400
TYPE_ID: int = 42
OTHER_TYPE_ID: int = 7

_APP: Flask = Flask(__name__)


def _read(reader: Any, query: str) -> Any:
    """Runs a reader inside a request carrying the query string"""
    with _APP.test_request_context(f'/?{query}'):
        return reader()


def _refusal(reader: Any, query: str) -> HTTPException:
    """The HTTPException a reader raises for the query string"""
    with pytest.raises(HTTPException) as refused:
        _read(reader, query)

    return refused.value


# ---------------------------------------------------- the type_id reader -------------------------------------------- #

class TestReadTemplateTypeIdParam:
    """type_id: a positive integer, None when absent"""

    def test_absent_is_none(self) -> None:
        """No parameter, no type condition"""
        assert _read(read_template_type_id_param, 'limit=0') is None

    @pytest.mark.parametrize('query, expected', [
        (f'type_id={TYPE_ID}', TYPE_ID),
        (f'type_id={OTHER_TYPE_ID}', OTHER_TYPE_ID),
        (f'type_id=%20{TYPE_ID}%20', TYPE_ID),
        ('type_id=1', 1),
    ], ids=['id', 'other-id', 'whitespace', 'smallest'])
    def test_a_positive_integer_is_read(self, query: str, expected: int) -> None:
        """Answered as an int"""
        assert _read(read_template_type_id_param, query) == expected

    @pytest.mark.parametrize('value', ['', 'abc', '0', '-1', '1.5', '1e3', '%2B5', '٣'],
                             ids=['empty', 'text', 'zero', 'negative', 'decimal', 'exponent', 'signed',
                                  'non-ascii-digit'])
    def test_anything_else_is_a_400_naming_it(self, value: str) -> None:
        """Refused, with the value as sent"""
        refused: HTTPException = _refusal(read_template_type_id_param, f'type_id={value}')

        assert refused.code == HTTP_BAD_REQUEST
        assert refused.description == TYPE_ID_INVALID_MSG.format(value=unquote(value))


# ---------------------------------------------------- the active reader --------------------------------------------- #

class TestReadTemplateActiveParam:
    """active: true / false by the flag rule, None when absent"""

    def test_absent_is_none(self) -> None:
        """Both active and deactivated templates are kept"""
        assert _read(read_template_active_param, 'limit=0') is None

    @pytest.mark.parametrize('value, expected', [('true', True), ('false', False), ('TRUE', True)])
    def test_the_flag_is_read(self, value: str, expected: bool) -> None:
        """Any casing of true / false"""
        assert _read(read_template_active_param, f'active={value}') is expected

    @pytest.mark.parametrize('value', ['', 'yes', '1'])
    def test_anything_else_is_a_400(self, value: str) -> None:
        """The empty value included - the caller meant something"""
        assert _refusal(read_template_active_param, f'active={value}').code == HTTP_BAD_REQUEST


# ------------------------------------------------ build_template_list_condition ------------------------------------- #

class TestBuildTemplateListCondition:
    """One equality condition, only the keys a parameter was given for"""

    def test_the_type_is_matched_on_the_dotted_path(self) -> None:
        """template_parameters.type, so a template with more parameter keys still matches"""
        assert TEMPLATE_TYPE_PATH == 'template_parameters.type'

    @pytest.mark.parametrize('type_id, active, expected', [
        (None, None, {}),
        (TYPE_ID, None, {'template_parameters.type': TYPE_ID}),
        (None, True, {'active': {'$in': [True, None]}}),
        (None, False, {'active': {'$nin': [True, None]}}),
        (OTHER_TYPE_ID, True, {'template_parameters.type': OTHER_TYPE_ID, 'active': {'$in': [True, None]}}),
    ], ids=['nothing', 'type', 'active', 'deactivated', 'both'])
    def test_the_condition(self, type_id: int | None, active: bool | None, expected: dict[str, Any]) -> None:
        """Absent parameters add nothing; false is a condition, not an absence"""
        assert build_template_list_condition(type_id, active) == expected
