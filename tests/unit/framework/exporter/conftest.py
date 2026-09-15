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
Shared fixtures for the exporter format unit tests
"""
from types import SimpleNamespace

import pytest
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture
def human_readable_object() -> SimpleNamespace:
    """A stand-in RenderResult with a labelled text field, a reference field and a location field.

    Shared by the CSV and XLSX human-readable export tests (function-scoped, so each test gets a fresh
    instance). Reference/location values are chosen so the resolved output is unambiguous:
    ref -> 'User #3 | alice', location(42) -> whatever the passed location_names map holds.
    """
    return SimpleNamespace(
        fields=[
            {'name': 'dg-name', 'type': 'text', 'value': 'host-1', 'label': 'Hostname'},
            {'name': 'owner', 'type': 'ref', 'value': 3, 'label': 'Owner',
             'reference': {'object_id': 3, 'type_label': 'User', 'summaries': [{'value': 'alice'}]}},
            {'name': 'dg_location', 'type': 'location', 'value': 42, 'label': 'Location'},
        ],
        sections=[],
        multi_data_sections=[],
        object_information={'object_id': 10, 'active': True},
        type_information={'type_id': 5, 'type_label': 'Server'},
    )
