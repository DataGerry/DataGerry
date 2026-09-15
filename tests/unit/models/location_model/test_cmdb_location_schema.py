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
Unit tests for the CmdbLocation validation schema

**Nothing consumes this schema.** No route validates a location body - the create route reads its
three ids with ``parse_required_int`` and assembles the document itself, and every other write is the
object mirror - so ``CmdbLocation.SCHEMA`` is documentation of the document rather than an enforced
contract. Whether it should be wired into the create route or dropped is discussion-backlog #221;
these tests pin what it currently *says*, so that decision is taken against a known baseline instead
of a guess.

What it says is worth pinning for a second reason: the schema is where the two nullable keys and the
two defaults of the document are written down, and the model was migrated onto the shared CmdbDAO
serialisation on 2026-09-10 - the tests below are what keeps the two descriptions of the same
document from drifting apart.
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import CmdbLocationDefault, LocationKey
# -------------------------------------------------------------------------------------------------------------------- #

SCHEMA: dict[str, Any] = CmdbLocation.SCHEMA


@pytest.fixture(name='validator')
def fixture_validator() -> Validator:
    """A validator over the schema, built the way APIBlueprint.validate would build it."""
    return Validator(SCHEMA, purge_unknown=True)


def _document(**overrides: Any) -> dict[str, Any]:
    """A location document as the mirror writes it."""
    document: dict[str, Any] = {
        LocationKey.PUBLIC_ID.value: 21,
        LocationKey.NAME.value: 'Room 42',
        LocationKey.PARENT.value: 1,
        LocationKey.OBJECT_ID.value: 88,
        LocationKey.TYPE_ID.value: 12,
        LocationKey.TYPE_LABEL.value: 'Room',
        LocationKey.TYPE_ICON.value: 'fas fa-door-open',
        LocationKey.TYPE_SELECTABLE.value: True,
    }
    document.update(overrides)

    return document


class TestTheDeclaredKeys:
    """The schema describes exactly the document the model serialises."""

    def test_it_declares_the_eight_payload_keys(self) -> None:
        """A key here that LocationKey does not name - or the reverse - is a drift between the two"""
        assert set(SCHEMA) == {key.value for key in LocationKey}

    def test_a_written_document_validates(self, validator: Validator) -> None:
        """The shape the object mirror stores has to be the shape the schema describes"""
        assert validator.validate(_document()) is True


class TestTheNullableTreeKeys:
    """``parent`` and ``object_id`` are nullable, and the tree code is written for that."""

    @pytest.mark.parametrize('key', [LocationKey.PARENT.value, LocationKey.OBJECT_ID.value])
    def test_a_null_is_accepted(self, validator: Validator, key: str) -> None:
        """
        A node may carry neither

        The delete path refuses to promote children onto a parentless node rather than writing them
        out of the tree - that guard exists because this is allowed here.
        """
        assert validator.validate(_document(**{key: None})) is True

    @pytest.mark.parametrize('key', [LocationKey.TYPE_ID.value, LocationKey.PUBLIC_ID.value])
    def test_the_other_integers_are_not_nullable(self, validator: Validator, key: str) -> None:
        """The root uses the 0 sentinel for its type, not a null"""
        assert validator.validate(_document(**{key: None})) is False


class TestTheOptionalRenderKeys:
    """``type_icon`` and ``type_selectable`` carry the defaults the model also applies."""

    def test_the_icon_default_matches_the_model(self) -> None:
        """Two places describe the same fallback, so they are asserted against one constant"""
        assert SCHEMA[LocationKey.TYPE_ICON.value]['default'] == CmdbLocationDefault.TYPE_ICON

    def test_the_selectable_default_matches_the_model(self) -> None:
        """A node is a valid drop target unless it says otherwise"""
        assert SCHEMA[LocationKey.TYPE_SELECTABLE.value]['default'] is CmdbLocationDefault.TYPE_SELECTABLE

    @pytest.mark.parametrize('key', [LocationKey.TYPE_ICON.value, LocationKey.TYPE_SELECTABLE.value])
    def test_an_omitted_key_is_filled_with_its_default(self, validator: Validator, key: str) -> None:
        """Cerberus normalises them in, which is the same answer the model's constructor gives"""
        document = _document()
        del document[key]

        assert validator.validate(document) is True
        assert validator.document[key] == SCHEMA[key]['default']

    def test_a_non_boolean_selectable_is_refused(self, validator: Validator) -> None:
        """The model refuses it too - the tree reads the flag as two-state"""
        assert validator.validate(_document(type_selectable='false')) is False

    def test_a_non_text_icon_is_refused(self, validator: Validator) -> None:
        """It reaches the frontend as a CSS class name"""
        assert validator.validate(_document(type_icon=7)) is False


class TestTheDisplayKeys:
    """``name`` and ``type_label`` are the two strings the tree renders."""

    @pytest.mark.parametrize('key', [LocationKey.NAME.value, LocationKey.TYPE_LABEL.value])
    def test_they_must_be_strings(self, validator: Validator, key: str) -> None:
        """Both are required by the model, so a non-string is refused on both descriptions"""
        assert validator.validate(_document(**{key: 5})) is False

    @pytest.mark.parametrize('key', [LocationKey.NAME.value, LocationKey.TYPE_LABEL.value])
    def test_the_schema_does_not_require_them(self, validator: Validator, key: str) -> None:
        """
        A gap between the two descriptions, recorded rather than fixed

        The MODEL requires them (REQUIRED_INIT_KEYS, live since 2026-09-10) while the schema does
        not, so a body validated here could still be refused by the model. Nothing validates a
        location body today, which is why this is a documentation question - see #221.
        """
        document = _document()
        del document[key]

        assert validator.validate(document) is True
