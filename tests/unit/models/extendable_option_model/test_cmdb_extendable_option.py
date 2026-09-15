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
Unit tests for cmdb.models.extendable_option_model.cmdb_extendable_option

One CmdbExtendableOption is one entry of one dropdown. The model had **no test module of its own**
until 2026-09-10: what ran of it did so through the functional route tests, which is why its three
hand-rolled `except` arms were the file's only uncovered statements.

Those three methods are gone - the model now declares `KEYS` and shares `CmdbDAO.from_data` /
`to_json` - so what is pinned here is the behaviour that migration has to preserve and the strictness
it adds: the round trip and its key order (a frontend contract), an OptionType member and its stored
string being interchangeable, `predefined` as a two-state flag, a document missing `value` or
`option_type` being refused instead of answered with nulls, and `to_json` refusing a foreign instance.
"""
from typing import Any

import pytest
from pymongo import IndexModel

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.extendable_option_model.cmdb_extendable_option import CmdbExtendableOption
from cmdb.models.extendable_option_model.extendable_option_constants import (
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
)
from cmdb.models.extendable_option_model.option_type_enum import OptionType

from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_extendable_option import (
    CmdbExtendableOptionInitError,
    CmdbExtendableOptionInitFromDataError,
    CmdbExtendableOptionToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
VALUE: str = 'CAT6'
OPTION_TYPE: str = OptionType.CABLE_TYPE.value


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored CmdbExtendableOption document, as the routes and the manager read it."""
    document: dict[str, Any] = {
        ExtendableOptionKey.PUBLIC_ID.value: PUBLIC_ID,
        ExtendableOptionKey.VALUE.value: VALUE,
        ExtendableOptionKey.OPTION_TYPE.value: OPTION_TYPE,
        ExtendableOptionKey.PREDEFINED.value: False,
    }
    document.update(overrides)

    return document


def _option(**overrides: Any) -> CmdbExtendableOption:
    """A CmdbExtendableOption built from a stored document."""
    return CmdbExtendableOption.from_data(_document(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the class contract                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheClassContract:
    """What the collection, the shared serialisation and the index reconciliation read off the class."""

    def test_the_collection_is_the_option_collection(self) -> None:
        """Every manager and updater addressing options resolves the name from here"""
        assert CmdbExtendableOption.COLLECTION == 'framework.extendableOptions'

    def test_the_key_enum_drives_the_shared_serialisation(self) -> None:
        """KEYS is what lets the model share from_data / to_json instead of implementing them"""
        assert CmdbExtendableOption.KEYS is ExtendableOptionKey
        assert 'from_data' not in vars(CmdbExtendableOption)
        assert 'to_json' not in vars(CmdbExtendableOption)

    def test_the_typed_errors_are_declared(self) -> None:
        """The shared implementation raises the model's own errors, not a generic one"""
        assert CmdbExtendableOption.INIT_FROM_DATA_ERROR is CmdbExtendableOptionInitFromDataError
        assert CmdbExtendableOption.TO_JSON_ERROR is CmdbExtendableOptionToJsonError

    def test_value_and_option_type_are_required_keys(self) -> None:
        """Without them a document names neither a dropdown nor an entry in it"""
        assert CmdbExtendableOption.REQUIRED_INIT_KEYS == [
            ExtendableOptionKey.VALUE.value,
            ExtendableOptionKey.OPTION_TYPE.value,
        ]

    def test_the_identity_index_is_unique_and_option_type_first(self) -> None:
        """(option_type, value) is the identity, and the prefix serves every 'all of this type' read"""
        declaration = CmdbExtendableOption.INDEX_KEYS[0]

        assert declaration['name'] == OPTION_TYPE_VALUE_INDEX_NAME
        assert declaration['unique'] is True
        assert [key for key, _ in declaration['keys']] == [
            ExtendableOptionKey.OPTION_TYPE.value,
            ExtendableOptionKey.VALUE.value,
        ]

    def test_the_declared_indexes_are_buildable(self) -> None:
        """CollectionValidator builds these, so a malformed declaration breaks the first boot"""
        indexes = CmdbExtendableOption.get_index_keys()

        assert all(isinstance(index, IndexModel) for index in indexes)
        assert OPTION_TYPE_VALUE_INDEX_NAME in {
            index.document['name'] for index in indexes
        }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the constructor                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """The validating place: what cannot be stored is refused before it reaches the database."""

    def test_the_values_are_stored_as_given(self) -> None:
        """Nothing is invented and nothing is dropped"""
        option = CmdbExtendableOption(public_id=PUBLIC_ID, value=VALUE, option_type=OPTION_TYPE, predefined=True)

        assert option.get_public_id() == PUBLIC_ID
        assert option.value == VALUE
        assert option.option_type == OPTION_TYPE
        assert option.predefined is True

    def test_an_option_type_member_is_stored_as_its_value(self) -> None:
        """The seeders and the ISMS importer build documents from the members, reads give strings"""
        option = CmdbExtendableOption(public_id=PUBLIC_ID, value=VALUE, option_type=OptionType.CABLE_TYPE)

        assert option.option_type == OptionType.CABLE_TYPE.value
        assert isinstance(option.option_type, str)

    def test_predefined_defaults_to_false(self) -> None:
        """An option is user-created unless it says otherwise"""
        assert CmdbExtendableOption(public_id=PUBLIC_ID, value=VALUE, option_type=OPTION_TYPE).predefined is False

    def test_a_null_predefined_is_false(self) -> None:
        """The flag is two-state: a stored null is 'not predefined', not a third state"""
        option = CmdbExtendableOption(
            public_id=PUBLIC_ID, value=VALUE, option_type=OPTION_TYPE, predefined=None
        )

        assert option.predefined is False

    @pytest.mark.parametrize('predefined', ['false', 0, 1, [], 'true'])
    def test_a_non_boolean_predefined_is_refused(self, predefined: Any) -> None:
        """Read for truthiness, a stored "false" would make the option undeletable"""
        with pytest.raises(CmdbExtendableOptionInitError):
            CmdbExtendableOption(
                public_id=PUBLIC_ID, value=VALUE, option_type=OPTION_TYPE, predefined=predefined
            )

    @pytest.mark.parametrize('value', [None, 3, ['CAT6'], {'value': 'CAT6'}])
    def test_a_non_text_value_is_refused(self, value: Any) -> None:
        """A value that is not text can neither be displayed nor matched against a stored selection"""
        with pytest.raises(CmdbExtendableOptionInitError):
            CmdbExtendableOption(public_id=PUBLIC_ID, value=value, option_type=OPTION_TYPE)

    def test_an_empty_value_is_accepted_by_the_model(self) -> None:
        """Emptiness is the schema's business: a read must not drop an option others may reference"""
        assert CmdbExtendableOption(public_id=PUBLIC_ID, value='', option_type=OPTION_TYPE).value == ''

    @pytest.mark.parametrize('public_id', [None, 0, -1, True, '7'])
    def test_an_unusable_public_id_is_refused(self, public_id: Any) -> None:
        """An option that cannot be addressed by a route is not an option; True would become id 1"""
        with pytest.raises(CmdbExtendableOptionInitError):
            CmdbExtendableOption(public_id=public_id, value=VALUE, option_type=OPTION_TYPE)

    def test_the_constructor_is_keyword_only(self) -> None:
        """CmdbDAO.__new__ reads public_id out of **kwargs, so a positional call never worked"""
        with pytest.raises(RequiredInitKeyNotFoundError):
            # pylint: disable=too-many-function-args
            CmdbExtendableOption(PUBLIC_ID, VALUE, OPTION_TYPE)  # type: ignore[misc]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            from_data / to_json (shared)                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFromData:
    """Reading a stored document, through the shared implementation."""

    def test_a_document_round_trips(self) -> None:
        """The four keys survive a read and a write unchanged"""
        assert CmdbExtendableOption.to_json(_option()) == _document()

    def test_the_mongo_id_is_not_carried_into_the_payload(self) -> None:
        """to_json emits exactly the enum's keys, which is what keeps '_id' out of a response"""
        option = CmdbExtendableOption.from_data(_document(_id='507f1f77bcf86cd799439011'))

        assert '_id' not in CmdbExtendableOption.to_json(option)

    def test_an_absent_predefined_key_reads_as_false(self) -> None:
        """A document written before the flag existed is still a user-created option"""
        document = _document()
        del document[ExtendableOptionKey.PREDEFINED.value]

        assert CmdbExtendableOption.from_data(document).predefined is False

    @pytest.mark.parametrize('missing', [ExtendableOptionKey.VALUE.value, ExtendableOptionKey.OPTION_TYPE.value])
    def test_a_document_missing_a_required_key_is_refused(self, missing: str) -> None:
        """It used to become an instance holding None, which the list route answered as 'value': null"""
        document = _document()
        del document[missing]

        with pytest.raises(CmdbExtendableOptionInitFromDataError):
            CmdbExtendableOption.from_data(document)

    def test_the_error_names_the_missing_key(self) -> None:
        """The message is what an operator has to work from when a document is drifted"""
        document = _document()
        del document[ExtendableOptionKey.VALUE.value]

        with pytest.raises(CmdbExtendableOptionInitFromDataError) as err:
            CmdbExtendableOption.from_data(document)

        assert ExtendableOptionKey.VALUE.value in str(err.value)

    def test_an_unreadable_value_is_refused(self) -> None:
        """The constructor's coercions run on the read path too"""
        with pytest.raises(CmdbExtendableOptionInitFromDataError):
            CmdbExtendableOption.from_data(_document(value=None))


class TestToJson:
    """Answering a document, through the shared implementation."""

    def test_the_key_order_is_the_enum_order(self) -> None:
        """The payload keys are a frontend contract, and the enum is where they are declared"""
        assert list(CmdbExtendableOption.to_json(_option())) == [key.value for key in ExtendableOptionKey]

    def test_a_foreign_instance_is_refused(self) -> None:
        """The guard the ISMS twins needed: a structurally similar object must not serialise as an option"""
        class Impostor:
            """Carries every attribute an option carries."""
            value = VALUE
            option_type = OPTION_TYPE
            predefined = False

            def get_public_id(self) -> int:
                """The accessor to_json reads the id through"""
                return PUBLIC_ID

        with pytest.raises(CmdbExtendableOptionToJsonError):
            CmdbExtendableOption.to_json(Impostor())  # type: ignore[arg-type]

    def test_a_dict_is_refused(self) -> None:
        """to_json takes an instance; handing it a raw document is a caller mistake, not a payload"""
        with pytest.raises(CmdbExtendableOptionToJsonError):
            CmdbExtendableOption.to_json(_document())  # type: ignore[arg-type]

    def test_it_is_a_cmdb_dao(self) -> None:
        """The version and public_id machinery every collection shares comes from there"""
        assert isinstance(_option(), CmdbDAO)
