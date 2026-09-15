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
Unit tests for IsmsImpactCategory

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own:

  - **the nested list is never None.** A category's ``impact_descriptions`` is maintained by the impact
    routes - creating an IsmsImpact pushes one entry into every category - so what the push writes into
    has to be a list. A category written before any impact existed carries no such key, and reading it
    as None produced a document its OWN schema rejects; it now reads as ``[]``
  - **a document without a name is refused on read**, through REQUIRED_INIT_KEYS, because the shared
    ``from_data`` reads with ``data.get()`` and would otherwise build a nameless category that cannot
    be written back
  - **the two key enums describe the two levels of the document**, and the schema is asserted against
    them rather than against a hand-written list
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_impact_category import IsmsImpactCategory
from cmdb.models.isms_model.isms_impact_category_constants import (
    IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS,
    ImpactCategoryKey,
    ImpactDescriptionKey,
)
from cmdb.class_schema.isms_model.isms_impact_category_schema import get_isms_impact_category_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_impact_category import (
    IsmsImpactCategoryInitError,
    IsmsImpactCategoryInitFromDataError,
    IsmsImpactCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 11
NAME: str = 'Financial'
SORT: int = 2
IMPACT_ID: int = 3
DESCRIPTION_TEXT: str = 'Losses above 100k'


def _description(impact_id: int = IMPACT_ID, value: str = DESCRIPTION_TEXT) -> dict[str, Any]:
    """One entry of the impact_descriptions list."""
    return {
        ImpactDescriptionKey.IMPACT_ID.value: impact_id,
        ImpactDescriptionKey.VALUE.value: value,
    }


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored IsmsImpactCategory document, as the collection holds it."""
    document: dict[str, Any] = {
        ImpactCategoryKey.PUBLIC_ID.value: PUBLIC_ID,
        ImpactCategoryKey.NAME.value: NAME,
        ImpactCategoryKey.IMPACT_DESCRIPTIONS.value: [_description()],
        ImpactCategoryKey.SORT.value: SORT,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
class TestTheKeySets:
    """Two enums, one per level of the document."""

    def test_the_schema_accepts_exactly_the_declared_keys(self) -> None:
        """A key in one and not the other is a field that never persists, or a rejected document"""
        assert set(get_isms_impact_category_schema()) == {key.value for key in ImpactCategoryKey}

    def test_the_nested_schema_accepts_exactly_the_entry_keys(self) -> None:
        """The description entries have their own shape, written down once"""
        nested = get_isms_impact_category_schema()[
            ImpactCategoryKey.IMPACT_DESCRIPTIONS.value]['schema']['schema']

        assert set(nested) == {key.value for key in ImpactDescriptionKey}

    def test_only_the_name_is_required_on_read(self) -> None:
        """
        impact_descriptions is deliberately NOT required

        A category that predates every impact carries none, and refusing to load it would make the
        impact scale unreadable rather than incomplete.
        """
        assert IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS == [ImpactCategoryKey.NAME.value]


class TestConstruction:
    """What a caller may and may not do."""

    def test_an_absent_description_list_becomes_empty(self) -> None:
        """
        The normalisation the impact routes depend on

        Creating an IsmsImpact pushes an entry into every category; pushing into None is not the same
        operation as pushing into an empty list, and the old None also failed the model's own schema.
        """
        category = IsmsImpactCategory(public_id=PUBLIC_ID, name=NAME)

        assert category.impact_descriptions == []

    def test_a_positional_call_is_refused_before_the_constructor(self) -> None:
        """
        Keyword-only: CmdbDAO.__new__ validates the init keys against the KEYWORD arguments and runs
        first, so a positional call fails on a public_id it cannot see
        """
        with pytest.raises(RequiredInitKeyNotFoundError):
            IsmsImpactCategory(PUBLIC_ID, NAME)  # pylint: disable=too-many-function-args

    def test_an_init_failure_surfaces_as_the_models_error(self) -> None:
        """The one except arm this model still owns"""
        class _Exploding:
            """A public_id the DAO cannot work with"""

        with pytest.raises(IsmsImpactCategoryInitError):
            IsmsImpactCategory(public_id=_Exploding(), name=NAME)


class TestTheDocumentRoundTrip:
    """from_data / to_json, inherited but exercised through this model's keys."""

    def test_a_stored_document_round_trips(self) -> None:
        """Every key survives both directions unchanged, nested entries included"""
        assert IsmsImpactCategory.to_json(IsmsImpactCategory.from_data(_document())) == _document()

    def test_a_category_without_descriptions_round_trips_validly(self) -> None:
        """
        The read/write asymmetry this migration closed

        Such a document used to load as `impact_descriptions: None` and serialise back into something
        the Cerberus schema rejects - a read the write path could not accept.
        """
        legacy = _document()
        legacy.pop(ImpactCategoryKey.IMPACT_DESCRIPTIONS.value)

        written = IsmsImpactCategory.to_json(IsmsImpactCategory.from_data(legacy))

        assert written[ImpactCategoryKey.IMPACT_DESCRIPTIONS.value] == []
        assert Validator(get_isms_impact_category_schema()).validate(
            {key: value for key, value in written.items() if value is not None}) is True

    def test_a_document_without_a_name_is_refused(self) -> None:
        """REQUIRED_INIT_KEYS: a nameless category cannot be written back, so it is not read in"""
        nameless = _document()
        nameless.pop(ImpactCategoryKey.NAME.value)

        with pytest.raises(IsmsImpactCategoryInitFromDataError):
            IsmsImpactCategory.from_data(nameless)

    def test_serialising_something_that_is_not_a_category_is_refused(self) -> None:
        """The guard the migration buys: the shared to_json type-checks its instance"""
        with pytest.raises(IsmsImpactCategoryToJsonError):
            IsmsImpactCategory.to_json(object())  # type: ignore[arg-type]


class TestTheSchema:
    """What the collection will accept."""

    def test_a_full_document_validates(self) -> None:
        """The ordinary case"""
        assert Validator(get_isms_impact_category_schema()).validate(_document()) is True

    def test_a_nameless_document_is_refused(self) -> None:
        """The one required field"""
        nameless = _document()
        nameless.pop(ImpactCategoryKey.NAME.value)

        assert Validator(get_isms_impact_category_schema()).validate(nameless) is False

    def test_a_description_entry_needs_an_integer_impact_id(self) -> None:
        """The entry points at an IsmsImpact by public_id, so text there is a broken reference"""
        broken = _document(impact_descriptions=[_description(impact_id='not-an-id')])

        assert Validator(get_isms_impact_category_schema()).validate(broken) is False

    def test_the_model_is_a_cmdb_dao(self) -> None:
        """The shared document machinery only applies to CmdbDAO subclasses"""
        assert issubclass(IsmsImpactCategory, CmdbDAO)
