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
Implementation of CmdbExtendableOption in DataGerry

One CmdbExtendableOption is **one selectable entry of one dropdown**: an `OptionType` names the
dropdown, `value` is the text a user picks, and `(option_type, value)` is the option's identity -
enforced by the unique compound index below, not by the routes' read-then-write guard.

Documents reach the collection from three places, only one of which passes the Cerberus schema:

* `POST` / `PUT /extendable_options/` - schema-validated, and the only path a user drives directly.
* the ISMS CSV importer, which creates the options a row references (`importer_isms_routes`).
* the two predefined-data seeders (`predefined_data/isms_data`, `predefined_data/port_data`), whose
  documents carry `predefined: True`.

`predefined` is what the routes gate on: an option DataGerry ships can neither be created, edited
nor deleted through the API. It is a two-state flag - an absent key or a stored `null` reads as
False - which `extendable_option_utils.coerce_predefined` is responsible for.

`ExtendableOptionKey` names every persisted key and drives the shared `CmdbDAO.from_data` /
`to_json`, so this model implements neither: the enum is the payload contract. The constructor is
the validating place and coerces through `extendable_option_utils`, which the list route's
normalisation shares - see that module for why a read accepts more than a write does.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.extendable_option_model.extendable_option_constants import (
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
)
from cmdb.models.extendable_option_model.extendable_option_utils import (
    coerce_option_type,
    coerce_option_value,
    coerce_predefined,
    coerce_public_id,
)

from cmdb.class_schema.extendable_option_model.cmdb_extendable_option_schema import get_cmdb_extendable_option_schema

from cmdb.errors.models.cmdb_extendable_option import (
    CmdbExtendableOptionInitError,
    CmdbExtendableOptionInitFromDataError,
    CmdbExtendableOptionToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbExtendableOption - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbExtendableOption(CmdbDAO):
    """
    Implementation of CmdbExtendableOption, one selectable value of one OptionType

    Extends: CmdbDAO
    """
    COLLECTION = "framework.extendableOptions"

    # The two keys a document must carry to be an option at all: without them it names neither a
    # dropdown nor an entry in it. Read through the shared from_data, which refuses such a document
    # instead of building an instance whose value is None - the shape the list route used to answer
    # as 'value': null
    REQUIRED_INIT_KEYS: list[str] = [
        ExtendableOptionKey.VALUE.value,
        ExtendableOptionKey.OPTION_TYPE.value,
    ]

    INDEX_KEYS: list[dict[str, Any]] = [
        # An option's identity is its value within its own list, and this index is the actual
        # guarantee. The create and update routes check first (extendable_options_helper.
        # option_value_exists), but that is a read-then-write, and the ISMS CSV importer resolves
        # values through its own read-then-insert - so before this index concurrent writers could
        # (and on installations older than 2026-07-06, without any check at all, did) leave two
        # identical entries in the same dropdown.
        #
        # Compound with option_type FIRST, so it is also a usable index for every 'all options of
        # this type' query - which is why the collection's former non-unique 'option_type' index was
        # dropped rather than kept beside it (updater_20260902).
        #
        # Case- and whitespace-sensitive, exactly like the route guard: 'CAT6', 'cat6' and ' CAT6'
        # are three different options. Existing databases are de-duplicated by updater_20260902
        # before it builds this index; changing INDEX_KEYS alone would have changed nothing for them,
        # since index reconciliation is name-based and purely additive
        {
            'keys': [
                (ExtendableOptionKey.OPTION_TYPE.value, CmdbDAO.DAO_ASCENDING),
                (ExtendableOptionKey.VALUE.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': OPTION_TYPE_VALUE_INDEX_NAME,
            'unique': True,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_extendable_option_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = ExtendableOptionKey
    INIT_FROM_DATA_ERROR = CmdbExtendableOptionInitFromDataError
    TO_JSON_ERROR = CmdbExtendableOptionToJsonError


    def __init__(
            self,
            *,
            public_id: int,
            value: str,
            option_type: OptionType | str,
            predefined: bool | None = False,
        ) -> None:
        """
        Initialises a CmdbExtendableOption

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the CmdbExtendableOption
            value (str): The option value, i.e. the text offered in the dropdown
            option_type (OptionType | str): The OptionType whose list this option belongs to. A
                                            member and the string it is stored as are both accepted;
                                            the value is what gets stored
            predefined (bool | None): True for an option DataGerry ships, which the routes refuse to
                                      create, edit or delete. None (an absent or null key) reads as
                                      False. Defaults to False

        Raises:
            CmdbExtendableOptionInitError: If the CmdbExtendableOption could not be initialised
        """
        try:
            self.value: str = coerce_option_value(value)
            self.option_type: str = coerce_option_type(option_type)
            self.predefined: bool = coerce_predefined(predefined)

            # Coerced here rather than left to CmdbDAO's int(): an option is always constructed from
            # a stored document or from the update route's URL id, so a missing or zero public_id is
            # a document that cannot be addressed - and it says so, instead of raising the int()
            # TypeError the caller then has to interpret
            super().__init__(public_id=coerce_public_id(public_id))
        except Exception as err:
            raise CmdbExtendableOptionInitError(err) from err
