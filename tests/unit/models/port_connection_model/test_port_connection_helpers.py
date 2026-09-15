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
Unit tests for cmdb.models.port_connection_model.port_connection_helpers

The sort invariant is the single most load-bearing line of the feature: it is what makes 'A to B' and
'B to A' one document, and therefore what lets the two partial unique indexes refuse a duplicate pair
at all. These tests pin it, plus the self-connection predicate the database provably cannot hold.

Pure tests: no Mongo, no Flask, no fixtures
"""
from typing import Any

import pytest

from cmdb.models.port_connection_model import coerce_endpoints, is_self_connection, sort_endpoints
# -------------------------------------------------------------------------------------------------------------------- #

PORT_A: int = 3
PORT_B: int = 10


class TestCoerceEndpoints:
    """Reading two port ids out of whatever a client sent."""

    def test_accepts_two_integers(self) -> None:
        """The ordinary case, left in the order it was given - coercion does not sort"""
        assert coerce_endpoints([PORT_B, PORT_A]) == [PORT_B, PORT_A]

    def test_accepts_a_tuple(self) -> None:
        """A stored document read back through a driver may hand over either sequence type"""
        assert coerce_endpoints((PORT_A, PORT_B)) == [PORT_A, PORT_B]

    @pytest.mark.parametrize('endpoints', [[3.0, 10.0], ['3', '10'], [3, '10']], ids=str)
    def test_accepts_the_notations_a_client_may_send(self, endpoints: Any) -> None:
        """A JSON client may send 3.0 and a CSV one '3'; both name port 3"""
        assert coerce_endpoints(endpoints) == [PORT_A, PORT_B]

    @pytest.mark.parametrize('endpoints', [[PORT_A], [PORT_A, PORT_B, 11], []], ids=str)
    def test_refuses_anything_but_two_ends(self, endpoints: Any) -> None:
        """
        A connection joins exactly two ports

        One or three ends do not name a connection, and no default could repair either.
        """
        assert coerce_endpoints(endpoints) is None

    @pytest.mark.parametrize('endpoints', [None, PORT_A, 'a,b', {'a': PORT_A}], ids=str)
    def test_refuses_a_value_that_is_not_a_sequence(self, endpoints: Any) -> None:
        """A raw request value can be anything at all, so nothing may raise"""
        assert coerce_endpoints(endpoints) is None

    @pytest.mark.parametrize('endpoints', [[PORT_A, 'x'], [None, PORT_B], [PORT_A, 1.5]], ids=str)
    def test_refuses_an_end_that_is_not_a_whole_number(self, endpoints: Any) -> None:
        """A port id is a public_id; half a port does not exist"""
        assert coerce_endpoints(endpoints) is None

    def test_refuses_booleans(self) -> None:
        """bool is an int subclass in Python, so True would otherwise pass as port 1"""
        assert coerce_endpoints([True, PORT_B]) is None


class TestSortEndpoints:
    """The canonical form - the feature's most load-bearing invariant."""

    def test_sorts_ascending(self) -> None:
        """The stored order is what makes the pair indexable as one key"""
        assert sort_endpoints([PORT_B, PORT_A]) == [PORT_A, PORT_B]

    def test_both_spellings_of_one_link_produce_the_same_pair(self) -> None:
        """
        This is what makes the connection undirected, structurally

        Without it 3-to-10 and 10-to-3 would be two documents, and 'no duplicate pair' would need an
        application check the database could not back.
        """
        assert sort_endpoints([PORT_A, PORT_B]) == sort_endpoints([PORT_B, PORT_A])

    def test_an_already_sorted_pair_is_unchanged(self) -> None:
        """Re-canonicalising a stored pair is a no-op, so a read-modify-write cannot drift"""
        assert sort_endpoints([PORT_A, PORT_B]) == [PORT_A, PORT_B]

    def test_a_self_connection_still_sorts(self) -> None:
        """Sorting judges nothing - refusing [5, 5] is the validator's job, with its own message"""
        assert sort_endpoints([5, 5]) == [5, 5]

    @pytest.mark.parametrize('endpoints', [None, [PORT_A], ['x', PORT_B]], ids=str)
    def test_reports_an_unusable_value_rather_than_guessing(self, endpoints: Any) -> None:
        """The caller refuses it; silently repairing it would store the wrong link"""
        assert sort_endpoints(endpoints) is None


class TestIsSelfConnection:
    """The one cardinality rule no index can hold."""

    def test_the_same_port_twice_is_a_self_connection(self) -> None:
        """
        [5, 5] dedupes to one key inside a single document

        A unique multikey index therefore sees nothing wrong with it, which is exactly why this stays
        a validator rule.
        """
        assert is_self_connection([5, 5]) is True

    def test_the_notation_does_not_hide_it(self) -> None:
        """'5' and 5 are the same port, so the check has to run on the coerced values"""
        assert is_self_connection([5, '5']) is True

    def test_two_different_ports_are_not(self) -> None:
        """The ordinary case"""
        assert is_self_connection([PORT_A, PORT_B]) is False

    @pytest.mark.parametrize('endpoints', [None, [5], ['x', 'x']], ids=str)
    def test_an_unusable_value_is_not_reported_as_a_self_connection(self, endpoints: Any) -> None:
        """It has its own, more accurate message - reporting both would name one fault twice"""
        assert is_self_connection(endpoints) is False
