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
Unit tests for cmdb.utils.error_chain.find_cause
"""
import pytest

from cmdb.utils import find_cause
# -------------------------------------------------------------------------------------------------------------------- #


class _Inner(Exception):
    """The kind of error looked for."""


class _SpecificInner(_Inner):
    """A subclass of it."""


class _Outer(Exception):
    """A wrapper."""


def _chain(*errors: BaseException) -> BaseException:
    """Links the errors outermost-first through __cause__, the way `raise ... from err` does."""
    for outer, inner in zip(errors, errors[1:]):
        outer.__cause__ = inner

    return errors[0]


def test_the_error_itself_counts() -> None:
    """A route catching the database error directly finds it without a chain."""
    err = _Inner('x')

    assert find_cause(err, _Inner) is err


def test_it_is_found_through_every_layer() -> None:
    """Manager error around BaseManager error around database error: depth does not matter."""
    inner = _Inner('x')

    assert find_cause(_chain(_Outer('a'), _Outer('b'), _Outer('c'), inner), _Inner) is inner


def test_a_subclass_counts_and_the_outermost_match_wins() -> None:
    """The first instance from the outside is answered."""
    near, far = _SpecificInner('near'), _Inner('far')

    assert find_cause(_chain(_Outer('a'), near, far), _Inner) is near


@pytest.mark.parametrize('chain', [
    lambda: _Outer('alone'),
    lambda: _chain(_Outer('a'), _Outer('b')),
], ids=['no-cause', 'no-match-in-the-chain'])
def test_no_match_is_none(chain) -> None:
    """Nothing of the kind anywhere."""
    assert find_cause(chain(), _Inner) is None


def test_the_implicit_context_is_not_followed() -> None:
    """Only `from err` states a cause; an error merely raised while handling another is unrelated."""
    try:
        try:
            raise _Inner('handled')
        except _Inner:
            raise _Outer('unrelated')  # pylint: disable=raise-missing-from
    except _Outer as err:
        assert err.__context__ is not None
        assert find_cause(err, _Inner) is None


def test_a_chain_that_loops_ends() -> None:
    """A cycle cannot hang the lookup."""
    first, second = _Outer('a'), _Outer('b')
    first.__cause__, second.__cause__ = second, first

    assert find_cause(first, _Inner) is None
