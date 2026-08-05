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
Unit tests for cmdb.framework.ipam.pagination

Pure tests: no Mongo, no Flask, no fixtures. Each clamp axis is exercised through its own
parametrize table so a regression against the page-size, page-floor, or last-page policy
fails loudly and points to the broken axis
"""
import pytest

from cmdb.framework.ipam.pagination import clamp_page
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                page_size clamping                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('page_size, expected_size', [
    (50, 50),
    (1, 1),
    (500, 500),
    (250, 250),
    (501, 500),
    (1000, 500),
    (0, 1),
    (-50, 1),
    (-1, 1),
])
def test_clamp_page_size_is_bounded_to_min_max(page_size: int, expected_size: int) -> None:
    """page_size is clamped to [MIN_PAGE_SIZE, MAX_PAGE_SIZE] regardless of total"""
    _, safe_size = clamp_page(page=1, page_size=page_size, total=1000)

    assert safe_size == expected_size


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  page clamping                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('page, expected_page', [
    (1, 1),
    (2, 2),
    (5, 5),
    (10, 10),
    (11, 10),
    (100, 10),
    (0, 1),
    (-3, 1),
])
def test_clamp_page_number_is_bounded_to_min_last(page: int, expected_page: int) -> None:
    """page is clamped to [MIN_PAGE, last_page]; total=500 + page_size=50 means last_page=10"""
    safe_page, _ = clamp_page(page=page, page_size=50, total=500)

    assert safe_page == expected_page


# -------------------------------------------------------------------------------------------------------------------- #
#                                              empty / negative total                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('total', [0, -1, -100])
def test_clamp_page_falls_back_to_min_page_when_no_items(total: int) -> None:
    """When total is zero or negative, page falls back to MIN_PAGE (1) regardless of input"""
    safe_page, _ = clamp_page(page=42, page_size=50, total=total)

    assert safe_page == 1


@pytest.mark.parametrize('total', [0, -5])
def test_clamp_page_size_still_clamped_when_no_items(total: int) -> None:
    """page_size clamping still applies even when total triggers the no-items fallback"""
    _, safe_size = clamp_page(page=1, page_size=9999, total=total)

    assert safe_size == 500


# -------------------------------------------------------------------------------------------------------------------- #
#                                              last_page boundary cases                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('total, page_size, expected_last_page', [
    (1, 50, 1),
    (50, 50, 1),
    (51, 50, 2),
    (99, 50, 2),
    (100, 50, 2),
    (101, 50, 3),
    (500, 50, 10),
    (501, 50, 11),
    (1, 1, 1),
    (1000, 1, 1000),
    (3, 2, 2),
    (4, 2, 2),
    (5, 2, 3),
])
def test_clamp_page_last_page_uses_ceiling_division(
    total: int,
    page_size: int,
    expected_last_page: int,
) -> None:
    """A page number past the end is clamped to last_page = ceil(total / page_size)"""
    safe_page, _ = clamp_page(page=10_000, page_size=page_size, total=total)

    assert safe_page == expected_last_page
