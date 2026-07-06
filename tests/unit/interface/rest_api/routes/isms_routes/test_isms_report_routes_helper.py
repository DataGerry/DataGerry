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
Unit tests for the sort_key control-measure ordering helper (isms_report_routes)

The helper is pure: it orders control measures ISO-27001:2022-source-first, then by a natural
(numeric-aware) identifier order, with empty identifiers last - and must never raise when
identifiers of different shapes are compared.
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.isms_report_routes import sort_key
# -------------------------------------------------------------------------------------------------------------------- #

ISO_SOURCE: str = 'ISO 27001:2022'


def _cm(source: str = 'Other', identifier: str = '') -> dict[str, Any]:
    """Builds a control-measure dict with the fields sort_key reads."""
    return {'source': source, 'identifier': identifier}


def _sorted_identifiers(control_measures: list[dict[str, Any]]) -> list[str]:
    """Returns the identifiers of the control measures in sort_key order."""
    return [cm['identifier'] for cm in sorted(control_measures, key=sort_key)]


def test_iso_source_sorts_first() -> None:
    """A control measure with the ISO 27001:2022 source is ordered before others."""
    control_measures = [_cm(source='Other', identifier='1'), _cm(source=ISO_SOURCE, identifier='9')]

    assert sorted(control_measures, key=sort_key)[0]['source'] == ISO_SOURCE


def test_empty_identifier_sorts_last() -> None:
    """Within the same source, an empty identifier is ordered after a non-empty one."""
    assert _sorted_identifiers([_cm(identifier=''), _cm(identifier='1')]) == ['1', '']


def test_identifiers_sort_numerically() -> None:
    """Identifier segments are compared numerically, so 5.2 precedes 5.10."""
    assert _sorted_identifiers([_cm(identifier='5.10'), _cm(identifier='5.2')]) == ['5.2', '5.10']


def test_heterogeneous_identifiers_do_not_raise() -> None:
    """Mixing numeric and alphabetic identifiers must not raise a TypeError (regression)."""
    control_measures = [_cm(identifier='A'), _cm(identifier='12'), _cm(identifier='A.1'), _cm(identifier='3')]

    ordered = _sorted_identifiers(control_measures)

    # Numeric identifiers sort before alphabetic ones (digit groups rank before non-digit groups)
    assert ordered == ['3', '12', 'A', 'A.1']
