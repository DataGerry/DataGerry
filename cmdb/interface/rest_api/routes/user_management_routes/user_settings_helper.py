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
The one shape every CmdbUserSetting route answers

A setting's identity is ``(user_id, resource)``; the ``public_id`` the shared insert path stamps on the stored
document is a storage artifact no client reads. So every route - create, list, single read, update, delete - answers
the same four keys the list read always answered: ``resource``, ``user_id``, ``payloads``, ``setting_type``.
"""
from typing import Any

from cmdb.models.settings_model import UserSettingKey, normalize_user_setting_document
# -------------------------------------------------------------------------------------------------------------------- #

# Keys the stored document carries that are not part of a setting: the id the shared insert path stamps, and
# MongoDB's own
STORAGE_ONLY_KEYS: frozenset[str] = frozenset({UserSettingKey.PUBLIC_ID.value, '_id'})


def serialize_user_setting(document: dict[str, Any]) -> dict[str, Any]:
    """
    Answers a stored or written CmdbUserSetting document in the settings routes' one shape

    The four normalised keys (``normalize_user_setting_document``: a missing payload list becomes an empty one, the
    scope its stored value). A stored document the normaliser cannot read - one this version never wrote, e.g. a
    scope it does not know - is answered as stored, minus the stamped ``public_id``, so a client can inspect what is
    wrong with it and overwrite or delete it; the normaliser has already logged it

    Args:
        document (dict[str, Any]): A stored CmdbUserSetting document, or a validated write body

    Returns:
        dict[str, Any]: The four keys, or an unreadable document's stored keys - never ``public_id``
    """
    normalized: dict[str, Any] | None = normalize_user_setting_document(document)

    if normalized is not None:
        return normalized

    return {key: value for key, value in document.items() if key not in STORAGE_ONLY_KEYS}
