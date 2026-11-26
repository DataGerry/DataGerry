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
The messages of the access rules' write rules - format strings where they carry a placeholder
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class AccessRuleMessage(BaseStrEnum):
    """
    What a refused access rule write says - every problem of one write is answered together
    """
    FIELD_CLASS_NAME_FIXED = (
        "The name of field class {public_id} cannot change - fields and scope roles reference it: '{stored}' stays!"
    )
    FIELD_CLASS_NAME_TAKEN = "A field class named '{name}' exists already!"
    SCOPE_ROLE_NAME_TAKEN = "A scope role named '{name}' exists already!"
    UNKNOWN_TYPES = "The scope role names Types that do not exist: {ids}"
    UNKNOWN_FIELD_CLASSES = "The scope role names field classes that do not exist: {names}"
    UNKNOWN_GROUP = "User group {group_id} does not exist!"
    UNKNOWN_ROLE = "Scope role {role_id} does not exist!"
    ASSIGNMENT_TAKEN = "User group {group_id} holds scope role {role_id} with this scope already!"
    FIELD_CLASS_IN_USE = (
        "Field class '{name}' cannot be deleted - the scope roles {role_ids} grant it: take it out of them first!"
    )
    FIELD_CLASS_ON_FIELDS = (
        "Field class '{name}' cannot be deleted - {count} field(s) carry it (see its usage): take it off them first!"
    )
    SCOPE_ROLE_IN_USE = (
        "Scope role {role_id} cannot be deleted - the assignments {assignment_ids} grant it: delete them first!"
    )
    GROUP_ASSIGNMENTS_DELETED = "the assignments of user group {group_id}"
    TYPES_LOCKED = "The change would leave Types {ids} readable by no user group - not even the administrators!"
    TYPES_OPENED = (
        "The change would open Types {ids} to every user group - send unrestrict=true to confirm!"
    )
    BEYOND_OWN_REACH = (
        "Scope role {role_id} would give a user group you are in more than you hold yourself: {beyond}"
    )
    BEYOND_DELEGATION = (
        "Scope role {role_id} grants more than your own access - you may delegate assignments only within it: {beyond}"
    )


class ReachPart(BaseStrEnum):
    """
    How a refusal names what a scope role grants beyond the caller's own reach
    """
    OPERATION = "{operation} on {types}"
    REGULAR_FIELDS = "writing fields on {types}"
    FIELD_CLASS = "writing the field class '{name}' on {types}"
    EVERY_TYPE = "every Type"
    TYPE_IDS = "Types {ids}"
    SEPARATOR = "; "
