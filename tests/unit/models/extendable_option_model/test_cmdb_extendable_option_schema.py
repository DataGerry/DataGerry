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
Unit tests for the CmdbExtendableOption validation schema

The schema is the write contract of the create and update routes, and it had no test of its own: it
appeared in the suite only as the decorator the functional route tests happened to pass through.
Validated here through the same Validator the blueprint builds (``purge_unknown=True``), because
what the routes receive is `validator.document`, not the raw body - which is also why the
`public_id` question matters: a key the schema declares is NOT purged, and until 2026-09-10 the
create route inserted it, letting a client choose an option's id.
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.extendable_option_model.cmdb_extendable_option import CmdbExtendableOption
from cmdb.models.extendable_option_model.extendable_option_constants import ExtendableOptionKey
from cmdb.models.extendable_option_model.option_type_enum import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

SCHEMA: dict[str, Any] = CmdbExtendableOption.SCHEMA


@pytest.fixture(name='validator')
def fixture_validator() -> Validator:
    """The validator the APIBlueprint.validate decorator builds for this schema."""
    return Validator(SCHEMA, purge_unknown=True)


def _body(**overrides: Any) -> dict[str, Any]:
    """A request body as the Angular service sends it."""
    body: dict[str, Any] = {
        ExtendableOptionKey.VALUE.value: 'CAT6',
        ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        ExtendableOptionKey.PREDEFINED.value: False,
    }
    body.update(overrides)

    return body


class TestTheDeclaredKeys:
    """The schema declares exactly the document's keys."""

    def test_it_declares_the_four_payload_keys(self) -> None:
        """A key the schema does not declare is purged before a route sees it"""
        assert set(SCHEMA) == {key.value for key in ExtendableOptionKey}


class TestAValidBody:
    """What the frontend sends."""

    def test_the_frontend_payload_validates(self, validator: Validator) -> None:
        """value + option_type + predefined is what extendable-option.service.ts posts"""
        assert validator.validate(_body()) is True

    def test_an_unknown_key_is_purged(self, validator: Validator) -> None:
        """The routes read validator.document, so an extra key never reaches the database"""
        validator.validate(_body(label='CAT6'))

        assert 'label' not in validator.document


class TestValue:
    """The option value."""

    def test_it_is_required(self, validator: Validator) -> None:
        """An option without a value is not an entry in any dropdown"""
        body = _body()
        del body[ExtendableOptionKey.VALUE.value]

        assert validator.validate(body) is False

    def test_an_empty_value_is_refused(self, validator: Validator) -> None:
        """The write contract is stricter than the read: an empty entry cannot be picked"""
        assert validator.validate(_body(value='')) is False

    def test_a_non_string_value_is_refused(self, validator: Validator) -> None:
        """The model refuses it too, but the schema is what answers 400 instead of 500"""
        assert validator.validate(_body(value=5)) is False


class TestOptionType:
    """Which list the option belongs to."""

    def test_it_is_required(self, validator: Validator) -> None:
        """Every option belongs to exactly one OptionType"""
        body = _body()
        del body[ExtendableOptionKey.OPTION_TYPE.value]

        assert validator.validate(body) is False

    @pytest.mark.parametrize('option_type', [option_type.value for option_type in OptionType])
    def test_every_option_type_value_is_allowed(self, validator: Validator, option_type: str) -> None:
        """The allowed list is generated from the enum, so a new member needs no schema change"""
        assert validator.validate(_body(option_type=option_type)) is True

    def test_an_undefined_option_type_is_refused(self, validator: Validator) -> None:
        """This is what keeps an option out of a dropdown that does not exist"""
        assert validator.validate(_body(option_type='NOT_AN_OPTION_TYPE')) is False


class TestPredefined:
    """The flag the routes gate on."""

    def test_it_is_required(self, validator: Validator) -> None:
        """Both write routes compare it against the stored flag, so the body must state it"""
        body = _body()
        del body[ExtendableOptionKey.PREDEFINED.value]

        assert validator.validate(body) is False

    def test_a_null_is_refused(self, validator: Validator) -> None:
        """The flag is two-state: the API never stores the third one"""
        assert validator.validate(_body(predefined=None)) is False

    def test_a_string_is_refused(self, validator: Validator) -> None:
        """"false" is truthy, and an option it created could never be deleted again"""
        assert validator.validate(_body(predefined='false')) is False


class TestPublicId:
    """The id, which the server owns."""

    def test_it_is_optional(self, validator: Validator) -> None:
        """A create body carries none; the update route sets it from the URL"""
        assert validator.validate(_body()) is True

    def test_it_is_not_purged_when_sent(self, validator: Validator) -> None:
        """Declared keys survive validation - which is why the create route pops it explicitly"""
        validator.validate(_body(public_id=5000))

        assert validator.document[ExtendableOptionKey.PUBLIC_ID.value] == 5000

    def test_zero_is_refused(self, validator: Validator) -> None:
        """CmdbDAO reads 0 as 'no public_id assigned'"""
        assert validator.validate(_body(public_id=0)) is False
