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
Unit tests for CmdbReportCategory

Pins the (de)serialization contract of the report category: the document round trip, the 'predefined'
default a document may omit, and the three error types the model raises instead of letting a raw
KeyError / TypeError escape - the arms the route layer maps onto its status codes.
"""
from typing import Any

import pytest

from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.errors.models.cmdb_report_category import (
    CmdbReportCategoryInitError,
    CmdbReportCategoryInitFromDataError,
    CmdbReportCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID: int = 3
CATEGORY_NAME: str = 'General'


def _category_document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete stored CmdbReportCategory document."""
    document: dict[str, Any] = {'public_id': CATEGORY_ID, 'name': CATEGORY_NAME, 'predefined': True}
    document.update(overrides)

    return document


def test_from_data_reads_a_complete_document() -> None:
    """Every stored key lands on the instance."""
    category = CmdbReportCategory.from_data(_category_document())

    assert category.public_id == CATEGORY_ID
    assert category.name == CATEGORY_NAME
    assert category.predefined is True


def test_from_data_defaults_predefined_to_false() -> None:
    """A document without 'predefined' hydrates as user-created, matching the schema default."""
    document = _category_document()
    del document['predefined']

    assert CmdbReportCategory.from_data(document).predefined is False


def test_from_data_without_a_public_id_raises() -> None:
    """CmdbDAO coerces the identity with int(), so a document without one cannot hydrate."""
    document = _category_document()
    del document['public_id']

    with pytest.raises(CmdbReportCategoryInitFromDataError):
        CmdbReportCategory.from_data(document)


def test_to_json_round_trips_a_document() -> None:
    """A stored document survives from_data -> to_json unchanged."""
    document = _category_document()

    assert CmdbReportCategory.to_json(CmdbReportCategory.from_data(document)) == document


def test_to_json_raises_for_an_incomplete_instance() -> None:
    """Serializing an instance whose attributes were stripped surfaces as the model's own error."""
    category = CmdbReportCategory.from_data(_category_document())
    del category.name

    with pytest.raises(CmdbReportCategoryToJsonError):
        CmdbReportCategory.to_json(category)


def test_init_wraps_a_failure_as_the_models_own_error() -> None:
    """A non-coercible identity fails inside __init__ and is wrapped, not leaked as a TypeError."""
    with pytest.raises(CmdbReportCategoryInitError):
        CmdbReportCategory(public_id='not-an-int', name=CATEGORY_NAME, predefined=False)


def test_collection_and_schema_are_exposed() -> None:
    """The model exposes its collection and the shared validation schema."""
    assert CmdbReportCategory.COLLECTION == 'framework.reportCategories'
    assert CmdbReportCategory.SCHEMA['name']['required'] is True
