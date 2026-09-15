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
Unit tests for APIParameters and the shared JSON-parameter parsing

``APIParameters`` is the base of every request-parameter class, and both of its classmethods were
entirely untested before 2026-08-27 (the file sat at 52%). ``from_data`` is now the ONE place the
JSON-valued query parameters are parsed - the three subclasses used to repeat that block - so these
tests are what pins that single implementation.
"""
import pytest

from cmdb.interface.rest_api.responses.response_parameters import APIParameters
from cmdb.interface.rest_api.responses.response_parameters.api_parameters import (
    JSON_PARAMETERS,
    parse_json_parameters,
)
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
# -------------------------------------------------------------------------------------------------------------------- #

QUERY_STRING: str = 'projection={"public_id":1}'


class TestParseJsonParameters:
    """The shared helper both parses in place and leaves everything else alone."""

    def test_parses_every_json_parameter(self) -> None:
        """filter and projection are the two JSON-valued query parameters."""
        optional = {ParameterKey.FILTER.value: '{"a": 1}', ParameterKey.PROJECTION.value: '{"b": 1}'}

        parse_json_parameters(optional)

        assert optional == {ParameterKey.FILTER.value: {'a': 1}, ParameterKey.PROJECTION.value: {'b': 1}}

    def test_leaves_absent_parameters_absent(self) -> None:
        """A parameter that was not sent is not invented."""
        optional: dict = {}

        parse_json_parameters(optional)

        assert not optional

    def test_leaves_other_parameters_untouched(self) -> None:
        """Route-specific args are not JSON and must survive verbatim."""
        optional = {'view': 'native', ParameterKey.LIMIT.value: '10'}

        parse_json_parameters(optional)

        assert optional == {'view': 'native', ParameterKey.LIMIT.value: '10'}

    @pytest.mark.parametrize('parameter', [key.value for key in JSON_PARAMETERS])
    def test_a_malformed_value_raises(self, parameter: str) -> None:
        """
        Deliberately unguarded: the parse_*_parameters decorator converts this into an HTTP 400

        Verified over HTTP: ?projection=not-json answers 400, so the caller already gets the right
        status without a guard here.
        """
        with pytest.raises(ValueError):
            parse_json_parameters({parameter: 'not json'})

    def test_a_list_shaped_json_value_is_accepted(self) -> None:
        """A filter may be a pipeline (list of stages), not only a criteria dict."""
        optional = {ParameterKey.FILTER.value: '[{"$match": {"a": 1}}]'}

        parse_json_parameters(optional)

        assert optional[ParameterKey.FILTER.value] == [{'$match': {'a': 1}}]


class TestApiParametersInit:
    """The constructor normalises its two values and keeps the rest as `optional`."""

    def test_defaults_are_empty_rather_than_none(self) -> None:
        """Callers read these attributes unconditionally, so None would be a trap."""
        params = APIParameters()

        assert params.query_string == ''
        assert not params.projection
        assert not params.optional

    def test_keeps_the_supplied_values(self) -> None:
        """A query string and a projection are stored as given."""
        params = APIParameters(QUERY_STRING, projection={'public_id': 1})

        assert params.query_string == QUERY_STRING
        assert params.projection == {'public_id': 1}

    def test_collects_unknown_parameters_into_optional(self) -> None:
        """Anything the class does not name rides along."""
        assert APIParameters(QUERY_STRING, view='native').optional == {'view': 'native'}

    def test_repr_names_all_three_values(self) -> None:
        """The repr is what shows up in a log line, so it has to carry the whole state."""
        text = repr(APIParameters(QUERY_STRING, projection={'a': 1}, view='native'))

        assert QUERY_STRING in text
        assert 'native' in text


class TestApiParametersFromData:
    """from_data is the entry point the parse_*_parameters decorators call."""

    def test_parses_the_projection_json(self) -> None:
        """The projection arrives as a JSON string in the query."""
        params = APIParameters.from_data('', **{ParameterKey.PROJECTION.value: '{"public_id": 1}'})

        assert params.projection == {'public_id': 1}

    def test_builds_an_instance_of_the_calling_class(self) -> None:
        """`cls` is the subclass, which is what lets the subclasses drop their own from_data."""
        class _Subclass(APIParameters):
            """A stand-in for a subclass that adds nothing."""

        assert isinstance(_Subclass.from_data(''), _Subclass)

    def test_a_malformed_projection_raises(self) -> None:
        """Converted into a 400 one level up."""
        with pytest.raises(ValueError):
            APIParameters.from_data('', **{ParameterKey.PROJECTION.value: '{'})


class TestApiParametersToDict:
    """to_dict was entirely untested; it is the base of the echoed `parameters` block."""

    def test_emits_the_query_string_and_optional(self) -> None:
        """`optional` used to be dropped here while both siblings included it."""
        params = APIParameters(QUERY_STRING, view='native')

        assert APIParameters.to_dict(params) == {
            ParameterKey.QUERY_STRING.value: QUERY_STRING,
            ParameterKey.OPTIONAL.value: {'view': 'native'},
        }

    def test_omits_the_projection_when_there_is_none(self) -> None:
        """An absent projection is left out rather than sent as {}."""
        assert ParameterKey.PROJECTION.value not in APIParameters.to_dict(APIParameters())

    def test_includes_the_projection_when_given(self) -> None:
        """A supplied projection is echoed back."""
        params = APIParameters(QUERY_STRING, projection={'public_id': 1})

        assert APIParameters.to_dict(params)[ParameterKey.PROJECTION.value] == {'public_id': 1}

    def test_is_callable_without_an_instance_of_the_class(self) -> None:
        """It is a staticmethod now - it never used `cls` - so it takes only the parameters object."""
        assert APIParameters.to_dict(APIParameters()) is not None
