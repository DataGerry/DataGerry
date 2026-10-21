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
Unit tests for cmdb.models.extendable_option_model.extendable_option_utils

The coercions the constructor and the list route share, and the read that answers a document without
building a model. Two properties matter beyond the individual values:

* what a **read** accepts is deliberately wider than what a write stores - an option whose OptionType
  the enum no longer names is answered, not hidden;
* an unreadable document is **skipped and reported**, never fatal: an option list fills a dropdown,
  so one drifted document must not cost a form every other value it offers.
"""
import logging
from typing import Any

import pytest

from cmdb.models.extendable_option_model.extendable_option_constants import ExtendableOptionKey
from cmdb.models.extendable_option_model.extendable_option_utils import (
    coerce_option_type,
    coerce_option_value,
    coerce_predefined,
    coerce_public_id,
    normalize_extendable_option_document,
)
from cmdb.models.extendable_option_model.option_type_enum import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 12
VALUE: str = 'Fibre LC'
OPTION_TYPE: str = OptionType.CABLE_TYPE.value


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored CmdbExtendableOption document."""
    document: dict[str, Any] = {
        ExtendableOptionKey.PUBLIC_ID.value: PUBLIC_ID,
        ExtendableOptionKey.VALUE.value: VALUE,
        ExtendableOptionKey.OPTION_TYPE.value: OPTION_TYPE,
        ExtendableOptionKey.PREDEFINED.value: True,
    }
    document.update(overrides)

    return document


class TestCoercePublicId:
    """The id every route addresses an option by."""

    def test_a_public_id_is_answered_unchanged(self) -> None:
        """The stored int is what every reference points at"""
        assert coerce_public_id(PUBLIC_ID) == PUBLIC_ID

    def test_zero_is_refused(self) -> None:
        """CmdbDAO reads 0 as 'no public_id assigned', and no route can address it"""
        with pytest.raises(ValueError):
            coerce_public_id(0)

    def test_a_bool_is_refused(self) -> None:
        """True is an int in Python: unguarded it would silently become option 1"""
        with pytest.raises(ValueError):
            coerce_public_id(True)

    @pytest.mark.parametrize('public_id', [None, '12', 12.0, -3, [12]])
    def test_anything_else_is_refused(self, public_id: Any) -> None:
        """A numeric string is refused too - the ids in this collection are written by the server"""
        with pytest.raises(ValueError):
            coerce_public_id(public_id)


class TestCoerceOptionValue:
    """The text a user picks in the dropdown."""

    def test_a_value_is_answered_unchanged(self) -> None:
        """Case and whitespace are significant: they are part of the option's identity"""
        assert coerce_option_value(' CAT6 ') == ' CAT6 '

    def test_an_empty_value_is_accepted(self) -> None:
        """Emptiness is the schema's business; dropping one here would hide a referenced option"""
        assert coerce_option_value('') == ''

    @pytest.mark.parametrize('value', [None, 5, True, ['CAT6'], {'value': 'CAT6'}])
    def test_a_non_string_is_refused(self, value: Any) -> None:
        """It could neither be displayed nor matched against a stored selection"""
        with pytest.raises(ValueError):
            coerce_option_value(value)


class TestCoerceOptionType:
    """Which dropdown the option belongs to."""

    def test_a_member_becomes_its_value(self) -> None:
        """The seeders and the ISMS importer build documents from the members"""
        assert coerce_option_type(OptionType.PORT_SPEED) == OptionType.PORT_SPEED.value

    def test_a_stored_string_is_answered_unchanged(self) -> None:
        """Everything read back from the database is a plain string"""
        assert coerce_option_type(OPTION_TYPE) == OPTION_TYPE

    def test_an_unknown_option_type_is_still_answered(self) -> None:
        """A read must not hide an option whose OptionType the enum no longer names"""
        assert coerce_option_type('RETIRED_TYPE') == 'RETIRED_TYPE'

    @pytest.mark.parametrize('option_type', [None, 7, True, ['PORT_TYPE']])
    def test_a_non_string_is_refused(self, option_type: Any) -> None:
        """Without a usable option_type the option belongs to no list at all"""
        with pytest.raises(ValueError):
            coerce_option_type(option_type)


class TestCoercePredefined:
    """The two-state flag the routes gate creation, editing and deletion on."""

    @pytest.mark.parametrize('predefined', [True, False])
    def test_a_boolean_is_answered_unchanged(self, predefined: bool) -> None:
        """Both states are meaningful: one is shipped by DataGerry, the other user-created"""
        assert coerce_predefined(predefined) is predefined

    def test_none_is_false(self) -> None:
        """An absent key and a stored null are the same statement: not predefined"""
        assert coerce_predefined(None) is False

    @pytest.mark.parametrize('predefined', ['false', 'true', 0, 1, [], {}])
    def test_a_non_boolean_is_refused(self, predefined: Any) -> None:
        """Read for truthiness, a stored "false" would make the option undeletable"""
        with pytest.raises(ValueError):
            coerce_predefined(predefined)


class TestNormalizeExtendableOptionDocument:
    """The read behind the list route."""

    def test_a_document_becomes_the_four_payload_keys(self) -> None:
        """Same keys, same order as the model's to_json - the payload is a frontend contract"""
        assert normalize_extendable_option_document(_document()) == {
            ExtendableOptionKey.PUBLIC_ID.value: PUBLIC_ID,
            ExtendableOptionKey.VALUE.value: VALUE,
            ExtendableOptionKey.OPTION_TYPE.value: OPTION_TYPE,
            ExtendableOptionKey.PREDEFINED.value: True,
        }

    def test_the_key_order_matches_the_enum(self) -> None:
        """The route answers these documents directly, so the order cannot drift from the model's"""
        normalized = normalize_extendable_option_document(_document())

        assert list(normalized) == [key.value for key in ExtendableOptionKey]

    def test_the_mongo_id_is_dropped(self) -> None:
        """This is what lets the route answer raw documents: '_id' never reaches a response"""
        normalized = normalize_extendable_option_document(_document(_id='507f1f77bcf86cd799439011'))

        assert '_id' not in normalized

    def test_an_unknown_stored_key_is_dropped(self) -> None:
        """The payload is exactly the enum's keys, so a drifted extra key cannot leak into it"""
        normalized = normalize_extendable_option_document(_document(legacy_label='CAT6'))

        assert 'legacy_label' not in normalized

    def test_an_absent_predefined_key_becomes_false(self) -> None:
        """A document written before the flag existed is a user-created option"""
        document = _document()
        del document[ExtendableOptionKey.PREDEFINED.value]

        assert normalize_extendable_option_document(document)[ExtendableOptionKey.PREDEFINED.value] is False

    def test_a_null_predefined_becomes_false(self) -> None:
        """The flag stays two-state on the read path too"""
        normalized = normalize_extendable_option_document(_document(predefined=None))

        assert normalized[ExtendableOptionKey.PREDEFINED.value] is False

    def test_an_option_type_member_is_normalised_to_its_value(self) -> None:
        """A seeded document may still hold the member it was built from"""
        normalized = normalize_extendable_option_document(_document(option_type=OptionType.PORT_TYPE))

        assert normalized[ExtendableOptionKey.OPTION_TYPE.value] == OptionType.PORT_TYPE.value

    @pytest.mark.parametrize('missing', [
        ExtendableOptionKey.PUBLIC_ID.value,
        ExtendableOptionKey.VALUE.value,
        ExtendableOptionKey.OPTION_TYPE.value,
    ])
    def test_a_document_missing_a_key_is_skipped(self, missing: str) -> None:
        """Skipped, not fatal: the rest of the dropdown still has to be answered"""
        document = _document()
        del document[missing]

        assert normalize_extendable_option_document(document) is None

    @pytest.mark.parametrize('override', [
        {ExtendableOptionKey.PUBLIC_ID.value: 0},
        {ExtendableOptionKey.VALUE.value: 5},
        {ExtendableOptionKey.OPTION_TYPE.value: None},
        {ExtendableOptionKey.PREDEFINED.value: 'false'},
    ])
    def test_an_unreadable_value_is_skipped(self, override: dict[str, Any]) -> None:
        """Every coercion's refusal ends the same way: this one option is left out"""
        assert normalize_extendable_option_document(_document(**override)) is None

    def test_a_skipped_document_is_reported_with_its_ids(self, caplog: pytest.LogCaptureFixture) -> None:
        """An operator has to be able to find the offending record"""
        with caplog.at_level(logging.WARNING):
            normalize_extendable_option_document(_document(value=None))

        assert str(PUBLIC_ID) in caplog.text
        assert OPTION_TYPE in caplog.text
