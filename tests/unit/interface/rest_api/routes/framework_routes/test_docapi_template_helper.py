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
Unit tests for the DocapiTemplate searchfilter check

Pure: no Mongo, no Flask app. `parse_template_searchfilter` is the only thing between the URL of
`GET /docapi/template/by/<searchfilter>` and the MongoDB query document, so what is pinned here is
that nothing but an equality match on a declared key gets through - in particular no operator that
runs JavaScript on the database server.
"""
import json
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    SEARCHFILTER_KEYS,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_helper import (
    is_searchfilter_scalar,
    parse_template_searchfilter,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400
TYPE_ID: int = 7
TEMPLATE_ID: int = 12

# The filter the frontend's document picker sends
PICKER_FILTER: dict[str, Any] = {DocapiTemplateKey.TEMPLATE_PARAMETERS.value: {'type': TYPE_ID}}

# The two ways to run JavaScript on the database server through a query document
WHERE_FILTER: dict[str, Any] = {'$where': 'sleep(1000) || true'}
FUNCTION_FILTER: dict[str, Any] = {
    '$expr': {'$function': {'body': 'function() { return true }', 'args': [], 'lang': 'js'}},
}


def _refused(filter_value: Any) -> HTTPException:
    """Runs the check on a filter that must be refused and returns the raised HTTPException."""
    with pytest.raises(HTTPException) as exc_info:
        parse_template_searchfilter(json.dumps(filter_value))

    assert exc_info.value.code == HTTP_BAD_REQUEST

    return exc_info.value


class TestAcceptedFilters:
    """What the route is for: equality matches on declared keys pass through unchanged."""

    def test_the_frontend_picker_filter_passes(self) -> None:
        """`{"template_parameters": {"type": <id>}}` is what the object view's picker asks for."""
        assert parse_template_searchfilter(json.dumps(PICKER_FILTER)) == PICKER_FILTER

    def test_a_public_id_match_passes(self) -> None:
        """A scalar match on a declared key is returned as parsed."""
        search: dict[str, Any] = {DocapiTemplateKey.PUBLIC_ID.value: TEMPLATE_ID}

        assert parse_template_searchfilter(json.dumps(search)) == search

    def test_an_empty_filter_passes(self) -> None:
        """An empty object matches every template, as it always did."""
        assert not parse_template_searchfilter('{}')

    @pytest.mark.parametrize('key', sorted(SEARCHFILTER_KEYS))
    def test_every_declared_key_accepts_a_scalar(self, key: str) -> None:
        """Each searchable key takes a scalar value."""
        assert parse_template_searchfilter(json.dumps({key: 'x'})) == {key: 'x'}

    def test_the_template_parameters_key_accepts_a_null(self) -> None:
        """A scalar for the nested key is fine too - it matches templates without parameters."""
        search: dict[str, Any] = {DocapiTemplateKey.TEMPLATE_PARAMETERS.value: None}

        assert parse_template_searchfilter(json.dumps(search)) == search


class TestRefusedFilters:
    """Everything that is not an equality match on a declared key is a 400."""

    def test_where_is_refused(self) -> None:
        """`$where` runs JavaScript on the database server."""
        assert '$where' in _refused(WHERE_FILTER).description

    def test_expr_with_function_is_refused(self) -> None:
        """`$expr` + `$function` runs JavaScript on the database server."""
        assert '$expr' in _refused(FUNCTION_FILTER).description

    def test_an_operator_inside_the_nested_key_is_refused(self) -> None:
        """The nested object is checked too: an operator one level down is still an operator."""
        search: dict[str, Any] = {DocapiTemplateKey.TEMPLATE_PARAMETERS.value: {'$where': 'true'}}

        assert '$where' in _refused(search).description

    def test_an_operator_as_a_value_is_refused(self) -> None:
        """`{"name": {"$regex": ...}}` is not an equality match."""
        _refused({DocapiTemplateKey.NAME.value: {'$regex': '.*'}})

    def test_an_object_value_on_a_scalar_key_is_refused(self) -> None:
        """Only `template_parameters` may hold an object."""
        _refused({DocapiTemplateKey.PUBLIC_ID.value: {'a': 1}})

    def test_a_list_value_is_refused(self) -> None:
        """A list would be an array match, not an equality match on a scalar."""
        _refused({DocapiTemplateKey.PUBLIC_ID.value: [1, 2]})

    def test_a_nested_non_scalar_value_is_refused(self) -> None:
        """Inside the nested object only scalars are allowed."""
        _refused({DocapiTemplateKey.TEMPLATE_PARAMETERS.value: {'type': {'nested': 1}}})

    def test_an_undeclared_key_is_refused_and_named(self) -> None:
        """A key the template does not declare as searchable is named in the 400."""
        assert "'template_data'" in _refused({DocapiTemplateKey.TEMPLATE_DATA.value: 'x'}).description

    @pytest.mark.parametrize('key', ['sort', 'direction', 'limit'])
    def test_the_manager_parameters_cannot_be_smuggled_in(self, key: str) -> None:
        """These names are keyword parameters of the manager read, not document keys."""
        _refused({key: 1})

    @pytest.mark.parametrize('raw', ['[]', '"text"', '5', 'null'])
    def test_a_filter_that_is_not_an_object_is_refused(self, raw: str) -> None:
        """Only a JSON object can be a query document."""
        with pytest.raises(HTTPException) as exc_info:
            parse_template_searchfilter(raw)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_invalid_json_is_refused(self) -> None:
        """A filter that does not parse is a 400, not a 500."""
        with pytest.raises(HTTPException) as exc_info:
            parse_template_searchfilter('not-json')

        assert exc_info.value.code == HTTP_BAD_REQUEST


@pytest.mark.parametrize('value, expected', [
    ('x', True), (1, True), (1.5, True), (True, True), (None, True),
    ({}, False), ([], False),
])
def test_is_searchfilter_scalar(value: Any, expected: bool) -> None:
    """Strings, numbers, booleans and null are scalars; objects and lists are not."""
    assert is_searchfilter_scalar(value) is expected
