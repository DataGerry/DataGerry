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
Unit tests for the numeric coercers of the ISMS write routes

Three routes normalise a client-supplied number to two decimals in place before the body reaches the
manager: `IsmsImpact` and `IsmsLikelihood` do it for `calculation_basis`, `IsmsRiskAssessment` for
`costs_for_implementation`. All three are the same shape - a `float(f"{float(x):.2f}")` in a `try`
with an `abort(400)` on anything that will not convert.

The two `calculation_basis` coercers are byte-identical twins in different modules, so they are
parametrised together here: a fix applied to one and not the other is exactly the mix-up this file
exists to catch. `calculation_basis` in particular is what the whole risk matrix is computed from, so
a value stored as a string would not fail at write time but at report time.
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.isms_routes.impact_routes import _coerce_calculation_basis as impact_coerce
from cmdb.interface.rest_api.routes.isms_routes.likelihood_routes import (
    _coerce_calculation_basis as likelihood_coerce,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_routes import _coerce_costs_for_implementation
# pylint: disable=use-implicit-booleaness-not-comparison
# `== {}` rather than `not data`: the point is that the coercer left the payload EXACTLY as it
# found it, not merely that it is falsey.
# -------------------------------------------------------------------------------------------------------------------- #

BASIS_KEY: str = 'calculation_basis'
COSTS_KEY: str = 'costs_for_implementation'

CALCULATION_BASIS_COERCERS = [
    pytest.param(impact_coerce, id='impact'),
    pytest.param(likelihood_coerce, id='likelihood'),
]


@pytest.mark.parametrize('coerce', CALCULATION_BASIS_COERCERS)
class TestCalculationBasisCoercion:
    """`calculation_basis` on IsmsImpact and IsmsLikelihood - two copies of one rule."""

    @pytest.mark.parametrize('raw, expected', [
        (1, 1.0), ('2.5', 2.5), (3.456, 3.46), (3.454, 3.45), (0, 0.0), (-1.5, -1.5),
    ], ids=str)
    def test_a_convertible_value_is_normalised_to_two_decimals(self, coerce, raw: Any, expected: float) -> None:
        """The scale is edited in a web form, so the value arrives as a string as often as a number."""
        data = {BASIS_KEY: raw}

        coerce(data)

        assert data[BASIS_KEY] == expected
        assert isinstance(data[BASIS_KEY], float)

    @pytest.mark.parametrize('raw', ['abc', '', None, [], {}, '1,5'], ids=str)
    def test_an_unconvertible_value_is_a_400(self, coerce, raw: Any) -> None:
        """
        Storing it unconverted would fail later, in the risk matrix

        The matrix multiplies these bases together; a string reaching that arithmetic surfaces as a
        report error with no connection to the write that caused it.
        """
        with pytest.raises(HTTPException) as excinfo:
            coerce({BASIS_KEY: raw})

        assert excinfo.value.code == 400

    def test_an_absent_key_is_a_400(self, coerce) -> None:
        """The bare subscript is deliberate - the field is required, not defaulted."""
        with pytest.raises(HTTPException) as excinfo:
            coerce({})

        assert excinfo.value.code == 400


class TestCostsForImplementationCoercion:
    """`costs_for_implementation` on IsmsRiskAssessment - the same rule, but optional."""

    @pytest.mark.parametrize('raw, expected', [(1, 1.0), ('2.5', 2.5), (3.456, 3.46)], ids=str)
    def test_a_convertible_value_is_normalised(self, raw: Any, expected: float) -> None:
        """Two decimals, because it is money."""
        data = {COSTS_KEY: raw}

        _coerce_costs_for_implementation(data)

        assert data[COSTS_KEY] == expected

    def test_an_absent_value_is_left_alone(self) -> None:
        """Unlike calculation_basis this field is optional - None means "not costed yet"."""
        data: dict[str, Any] = {COSTS_KEY: None}

        _coerce_costs_for_implementation(data)

        assert data[COSTS_KEY] is None

    def test_a_missing_key_is_left_alone(self) -> None:
        """A payload that never mentions costs is valid."""
        data: dict[str, Any] = {}

        _coerce_costs_for_implementation(data)

        assert data == {}

    @pytest.mark.parametrize('raw', ['abc', '', [], {}], ids=str)
    def test_an_unconvertible_value_is_a_400(self, raw: Any) -> None:
        """Optional is not the same as unvalidated: a value that was sent has to be usable."""
        with pytest.raises(HTTPException) as excinfo:
            _coerce_costs_for_implementation({COSTS_KEY: raw})

        assert excinfo.value.code == 400
