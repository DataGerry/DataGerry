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
The write rules of a field class: its name is fixed once stored and unique
"""
from typing import Any

from cmdb.manager.field_classes_manager import FieldClassesManager
from cmdb.models.access_model import FieldClassKey
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
from cmdb.framework.access_rules.access_rule_reads import clashes
# -------------------------------------------------------------------------------------------------------------------- #


def field_class_name_change(stored: dict[str, Any], body: dict[str, Any]) -> str | None:
    """
    Refuses an update renaming a field class - fields and scope roles reference it by name. A body leaving the name
    out, or sending the stored one, changes nothing

    Args:
        stored (dict[str, Any]): The field class as stored
        body (dict[str, Any]): The update's body

    Returns:
        str | None: The problem, or None when the name stays
    """
    stored_name: str = stored[FieldClassKey.NAME.value]
    sent: Any = body.get(FieldClassKey.NAME.value, stored_name)

    if sent == stored_name:
        return None

    return AccessRuleMessage.FIELD_CLASS_NAME_FIXED.value.format(
        public_id=stored[FieldClassKey.PUBLIC_ID.value], stored=stored_name,
    )


def field_class_name_taken(manager: FieldClassesManager, name: str) -> str | None:
    """
    Refuses a new field class under a name another one carries - one count. An update cannot rename, so only the
    create asks

    Args:
        manager (FieldClassesManager): The field classes of the request's database
        name (str): The name the new class would carry

    Raises:
        BaseManagerGetError: When the count fails

    Returns:
        str | None: The problem, or None when the name is free
    """
    if clashes(manager, {FieldClassKey.NAME.value: name}):
        return AccessRuleMessage.FIELD_CLASS_NAME_TAKEN.value.format(name=name)

    return None
