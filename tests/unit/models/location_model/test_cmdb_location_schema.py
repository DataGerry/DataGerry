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

**The schema is the stored document's contract, not a request validator.** No write runs it - the create route
takes three ids and an optional name and builds the rest, every other write is the object mirror - so what these
tests hold is that the schema TELLS THE TRUTH about the document the model reads: it requires exactly the keys
``CmdbLocation.REQUIRED_INIT_KEYS`` requires (the read path refuses a document without one), the two tree keys may be
null but not absent, its two defaults are ``CmdbLocationDefault``'s, and a document as the mirror writes it - the
root included - validates. A change to either description that the other does not follow fails here
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.location_model.cmdb_location_schema import get_cmdb_location_schema
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.database.predefined_data.cmdb_data.cmdb_location_data import get_root_location_data
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


class TestTheRequiredKeys:
    """The schema requires what the model requires - no more, no less."""

    def test_the_required_set_is_the_models(self) -> None:
        """The drift guard: the schema's required keys ARE CmdbLocation.REQUIRED_INIT_KEYS"""
        required: set[str] = {key for key, rules in SCHEMA.items() if rules.get('required')}

        assert required == set(CmdbLocation.REQUIRED_INIT_KEYS)

    @pytest.mark.parametrize('key', CmdbLocation.REQUIRED_INIT_KEYS)
    def test_a_document_without_a_required_key_is_refused(self, validator: Validator, key: str) -> None:
        """The schema refuses what the read path refuses"""
        document = _document()
        del document[key]

        assert validator.validate(document) is False
        assert key in validator.errors

    @pytest.mark.parametrize('key', [LocationKey.PARENT.value, LocationKey.OBJECT_ID.value])
    def test_a_tree_key_may_be_null_but_not_absent(self, validator: Validator, key: str) -> None:
        """No writer stores a null, but the tree code tolerates one; an absent key is a broken node"""
        assert validator.validate(_document(**{key: None})) is True

        document = _document()
        del document[key]

        assert validator.validate(document) is False

    @pytest.mark.parametrize('key', [LocationKey.PUBLIC_ID.value, LocationKey.TYPE_ICON.value,
                                     LocationKey.TYPE_SELECTABLE.value])
    def test_the_other_keys_are_optional(self, validator: Validator, key: str) -> None:
        """public_id is the server's, the two render keys default"""
        document = _document()
        del document[key]

        assert validator.validate(document) is True

    def test_the_seeded_root_validates(self, validator: Validator) -> None:
        """The root the database is seeded with - the 0 sentinels for parent, object and type - is a valid document"""
        assert validator.validate(get_root_location_data()) is True

    def test_what_the_schema_accepts_the_model_reads(self, validator: Validator) -> None:
        """The two descriptions agree in the direction that matters: a schema-valid document builds a model"""
        document = _document()
        assert validator.validate(document) is True

        location = CmdbLocation.from_data(validator.document)

        assert location.name == document[LocationKey.NAME.value]


class TestTheSpelling:
    """The schema names its keys and defaults through the model's constants."""

    def test_every_key_is_a_location_key(self) -> None:
        """No bare string: each key is one LocationKey names"""
        assert all(key in {member.value for member in LocationKey} for key in SCHEMA)

    def test_the_builder_answers_a_new_dict_each_call(self) -> None:
        """A caller mutating its copy cannot change the next one"""
        first = get_cmdb_location_schema()
        first[LocationKey.NAME.value]['required'] = False

        assert get_cmdb_location_schema()[LocationKey.NAME.value]['required'] is True
