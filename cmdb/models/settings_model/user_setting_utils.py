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
Reading a stored CmdbUserSetting document, defensively

The read path of the settings collection has one property the write path does not: it sees **every**
document a user has, including ones this version of DataGerry did not write. Until 2026-09-09 a single
unreadable document therefore cost the user their whole settings list - `get_user_settings` built a
model per document and one bad `setting_type` failed the entire read with a 400, for every other
setting too. The frontend syncs those settings on login and only logs the failure, so the visible
symptom was table layouts and dashboard state quietly never being restored.

So the read normalises instead of parsing: `normalize_user_setting_document` answers the document in
the shape the list route sends, or **None** for one it cannot read - which the manager skips and logs,
naming the resource so the offending record can be found. Pure, so both halves are unit-testable
without a database.

The write path still goes through the model (and now through the schema, which allows only the three
`UserSettingType` values), because a value the API accepts must be one the read can return
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.settings_model.user_setting_constants import UserSettingKey
from cmdb.models.settings_model.user_setting_type_enum import UserSettingType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'coerce_setting_type',
    'coerce_user_id',
    'coerce_payloads',
    'normalize_user_setting_document',
]


def coerce_setting_type(setting_type: Any) -> UserSettingType:
    """
    Resolves a stored or supplied scope into a UserSettingType member

    The one place the string <-> member conversion happens, so a member and the string it was stored
    as are equally acceptable everywhere a setting is constructed

    Args:
        setting_type (Any): A UserSettingType member, or the value one was stored as

    Raises:
        ValueError: If the value is not one of the three UserSettingType values

    Returns:
        UserSettingType: The matching member
    """
    if isinstance(setting_type, UserSettingType):
        return setting_type

    return UserSettingType(setting_type)


def coerce_user_id(user_id: Any) -> int:
    """
    Resolves the owning user's public_id

    Coerces the numeric string a client may send, and refuses everything else instead of letting a
    bare `int()` raise a TypeError the caller has to interpret. A bool is refused on purpose: `int(True)`
    is 1, which would silently claim user 1's settings

    Args:
        user_id (Any): The value stored or supplied as the owner's public_id

    Raises:
        ValueError: If the value is not usable as a user public_id

    Returns:
        int: The owner's public_id
    """
    if isinstance(user_id, bool) or not isinstance(user_id, (int, str)):
        raise ValueError(f"Not a usable user_id: {user_id!r}!")

    return int(user_id)


def coerce_payloads(payloads: Any) -> list[dict[str, Any]]:
    """
    Resolves the stored payload list

    A document may legally carry no payloads at all (the key is optional), and a stored `null` is the
    same statement - both answer an empty list rather than making the read fail

    Args:
        payloads (Any): The value stored under 'payloads'

    Raises:
        ValueError: If a value is present but is not a list

    Returns:
        list[dict[str, Any]]: The payload entries, as stored
    """
    if payloads is None:
        return []

    if not isinstance(payloads, list):
        raise ValueError(f"Not a usable payloads list: {payloads!r}!")

    return payloads


def normalize_user_setting_document(document: dict[str, Any]) -> dict[str, Any] | None:
    """
    Answers one stored document in the shape the settings list route sends

    The read-side counterpart of the model: same four keys, same normalisation (a missing payload list
    becomes an empty one), and no model instance built for a payload that is handed straight back.
    A document that cannot be read is reported and skipped by the caller rather than failing the whole
    list - see the module docstring for what that used to cost

    Args:
        document (dict[str, Any]): A stored CmdbUserSetting document

    Returns:
        dict[str, Any] | None: The four answer keys, or None when the document cannot be read
    """
    try:
        return {
            UserSettingKey.RESOURCE.value: document[UserSettingKey.RESOURCE.value],
            UserSettingKey.USER_ID.value: coerce_user_id(document.get(UserSettingKey.USER_ID.value)),
            UserSettingKey.PAYLOADS.value: coerce_payloads(document.get(UserSettingKey.PAYLOADS.value)),
            UserSettingKey.SETTING_TYPE.value: coerce_setting_type(
                document.get(UserSettingKey.SETTING_TYPE.value)
            ).value,
        }
    except (KeyError, ValueError) as err:
        LOGGER.warning(
            "[normalize_user_setting_document] Skipping an unreadable UserSetting "
            "(resource: %r, user_id: %r): %s",
            document.get(UserSettingKey.RESOURCE.value), document.get(UserSettingKey.USER_ID.value), err,
        )

        return None
