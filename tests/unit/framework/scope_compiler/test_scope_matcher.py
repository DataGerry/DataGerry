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
Unit tests for the in-memory matcher's ``$elemMatch`` - on documents as before, on scalar elements since phase 10 (an
address range on ``_scope.ips``); the equivalence with MongoDB is pinned by the integration suite
"""
from typing import Any

import pytest

from cmdb.framework.scope_compiler import document_matches
# -------------------------------------------------------------------------------------------------------------------- #

RANGE: dict[str, Any] = {'_scope.ips': {'$elemMatch': {'$gte': '4:0a000000', '$lte': '4:0affffff'}}}


@pytest.mark.parametrize('document, expected', [
    ({'_scope': {'ips': ['4:0a000001']}}, True),
    ({'_scope': {'ips': ['4:09ffffff', '4:0b000000']}}, False),
    ({'_scope': {'ips': ['4:0a000000', '4:0affffff']}}, True),
    ({'_scope': {'ips': []}}, False),
    ({'_scope': {}}, False),
    ({}, False),
    ({'_scope': {'ips': '4:0a000001'}}, False),
    ({'_scope': {'ips': [{'x': 1}, ['4:0a000001']]}}, False),
], ids=['inside', 'around-it', 'both-bounds', 'empty', 'no-list', 'no-block', 'not-an-array', 'no-scalar'])
def test_a_scalar_elem_match_needs_one_element_inside(document: dict[str, Any], expected: bool) -> None:
    """One element must satisfy both bounds - two elements each satisfying one do not"""
    assert document_matches(document, RANGE) is expected


def test_a_document_elem_match_is_unchanged() -> None:
    """Conditions on the element's fields"""
    criteria = {'fields': {'$elemMatch': {'name': 'size', 'value': {'$gt': 3}}}}

    assert document_matches({'fields': [{'name': 'size', 'value': 4}]}, criteria) is True
    assert document_matches({'fields': [{'name': 'size', 'value': 2}, 7]}, criteria) is False
