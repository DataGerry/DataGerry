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
Reading and coercing a stored CmdbExtendableOption document

Two callers share these coercions, which is why they live outside the model:

* ``CmdbExtendableOption.__init__`` - the write path and every single-document read. The constructor
  is the validating place, so a value that cannot be stored is refused there rather than reaching
  the database.
* ``normalize_extendable_option_document`` - the read behind the list route, which answers a whole
  option list at once. It normalises instead of building a model, and a document it cannot read is
  **skipped and reported** rather than failing the request: an option list is what fills a dropdown,
  so one drifted document must not cost a form every other value it offers (the same rule the
  settings list learned on 2026-09-09, see ``user_setting_utils``).

Which values are accepted here is deliberately wider than what the REST API stores. The Cerberus
schema owns the write contract - a non-empty value, an ``option_type`` that names a defined
``OptionType`` - while a read must still answer a document written by an older version, or by one of
the paths that insert documents directly (the ISMS CSV importer and the two predefined-data seeders).
An option whose ``option_type`` the ``OptionType`` enum no longer names is therefore returned, not
dropped: it belongs to no dropdown any more, but it is the delete route's business to remove it, not
the read's to hide it.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.extendable_option_model.extendable_option_constants import ExtendableOptionKey
from cmdb.models.extendable_option_model.option_type_enum import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'coerce_public_id',
    'coerce_option_value',
    'coerce_option_type',
    'coerce_predefined',
    'normalize_extendable_option_document',
]


def coerce_public_id(public_id: Any) -> int:
    """
    Resolves the option's own public_id

    Refuses a bool explicitly: it is an int in Python, so ``True`` would silently become option 1.
    Zero is refused as well - CmdbDAO treats it as "no public_id assigned" and the schema requires
    at least 1, so a document carrying it cannot be addressed by any route

    Args:
        public_id (Any): The value stored under 'public_id'

    Raises:
        ValueError: If the value cannot be used as a public_id

    Returns:
        int: The option's public_id
    """
    if isinstance(public_id, bool) or not isinstance(public_id, int) or public_id < 1:
        raise ValueError(f"Not a usable public_id: {public_id!r}!")

    return public_id


def coerce_option_value(value: Any) -> str:
    """
    Resolves the option's value, the text a user picks in the dropdown

    Emptiness is not judged here - the schema refuses an empty value on the write path, and a read
    that dropped one would remove an option other documents may already reference. Only a value that
    is not text at all is refused, because it cannot be displayed or matched against a stored
    selection

    Args:
        value (Any): The value stored under 'value'

    Raises:
        ValueError: If the value is not a string

    Returns:
        str: The option value, as stored
    """
    if not isinstance(value, str):
        raise ValueError(f"Not a usable option value: {value!r}!")

    return value


def coerce_option_type(option_type: Any) -> str:
    """
    Resolves which option list the option belongs to, as the string it is stored as

    An OptionType member and the string it is stored as are equally acceptable: the predefined-data
    seeders and the ISMS importer build documents from the members, while everything read back from
    the database is a plain string. Membership itself is not checked - see the module docstring for
    why a read answers an option whose type the enum no longer names

    Args:
        option_type (Any): The value stored under 'option_type'

    Raises:
        ValueError: If the value is neither an OptionType nor a string

    Returns:
        str: The OptionType value
    """
    if isinstance(option_type, OptionType):
        return option_type.value

    if not isinstance(option_type, str):
        raise ValueError(f"Not a usable option_type: {option_type!r}!")

    return option_type


def coerce_predefined(predefined: Any) -> bool:
    """
    Resolves whether DataGerry ships the option rather than a user having created it

    An absent key and a stored ``null`` are the same statement - "not predefined" - and both answer
    False, so the flag stays the two-state property the routes treat it as: predefined options
    cannot be created, edited or deleted through the API. Anything that is not a boolean is refused
    instead of being read for truthiness, because a stored ``"false"`` would otherwise make an
    option undeletable

    Args:
        predefined (Any): The value stored under 'predefined', if any

    Raises:
        ValueError: If a value is present but is not a boolean

    Returns:
        bool: True if the option is shipped by DataGerry, otherwise False
    """
    if predefined is None:
        return False

    if not isinstance(predefined, bool):
        raise ValueError(f"Not a usable predefined flag: {predefined!r}!")

    return predefined


def normalize_extendable_option_document(document: dict[str, Any]) -> dict[str, Any] | None:
    """
    Answers one stored document in the shape the option list route sends

    The read-side counterpart of the model: the same four keys in the same order, the same
    coercions, and no model instance built for a document that is handed straight back. Keys the
    document carries beyond those four - ``_id`` above all - are dropped here, which is what lets
    the route answer raw documents at all

    A document that cannot be read is reported and skipped by the caller. See the module docstring
    for why that is not a failure

    Args:
        document (dict[str, Any]): A stored CmdbExtendableOption document

    Returns:
        dict[str, Any] | None: The four answer keys, or None when the document cannot be read
    """
    try:
        return {
            ExtendableOptionKey.PUBLIC_ID.value: coerce_public_id(
                document[ExtendableOptionKey.PUBLIC_ID.value]
            ),
            ExtendableOptionKey.VALUE.value: coerce_option_value(
                document[ExtendableOptionKey.VALUE.value]
            ),
            ExtendableOptionKey.OPTION_TYPE.value: coerce_option_type(
                document[ExtendableOptionKey.OPTION_TYPE.value]
            ),
            ExtendableOptionKey.PREDEFINED.value: coerce_predefined(
                document.get(ExtendableOptionKey.PREDEFINED.value)
            ),
        }
    except (KeyError, ValueError) as err:
        LOGGER.warning(
            "[normalize_extendable_option_document] Skipping an unreadable CmdbExtendableOption "
            "(public_id: %r, option_type: %r): %s",
            document.get(ExtendableOptionKey.PUBLIC_ID.value),
            document.get(ExtendableOptionKey.OPTION_TYPE.value),
            err,
        )

        return None
