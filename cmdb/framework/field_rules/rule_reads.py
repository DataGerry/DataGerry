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
The reads behind applying the Field Rules to an object write

The active rules are read once per request and tenant (the bulk writes and the import share them); the writing user's
person only when a rule covering the object's Type sets ``${user.person}``. Nothing is read for a Type no rule covers
beyond the one rule read
"""
from collections.abc import Collection
from datetime import datetime, timezone
from typing import Any

from cmdb.manager import FieldRulesManager, ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import FieldRuleKey
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.user_model import CmdbUser
from cmdb.utils.request_scoped_cache import request_cache
from cmdb.framework.scope_compiler import ScopeReferences, ScopeResolver
from cmdb.framework.field_rules.field_rule_constants import RuleToken
from cmdb.framework.field_rules.rule_engine import RuleApplication, apply_rules, rules_on_type
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'load_active_rules',
    'run_field_rules',
]

# The request attribute the active rules are kept under, per tenant database
RULES_CACHE_KEY: str = 'field_rules_cache'


def load_active_rules(user: CmdbUser) -> list[dict[str, Any]]:
    """
    The active Field Rules of the user's tenant, read once per request

    Args:
        user (CmdbUser): The writing user - names the tenant

    Raises:
        FieldRulesManagerGetError: When the read fails (a failed read is not kept)

    Returns:
        list[dict[str, Any]]: The rules, ascending by public_id
    """
    cache: dict[Any, Any] | None = request_cache(RULES_CACHE_KEY)
    key: str | None = ManagerProvider.tenant_database(user)

    if cache is not None and key in cache:
        return cache[key]

    manager: FieldRulesManager = ManagerProvider.get_manager(ManagerType.FIELD_RULES, user)
    rules: list[dict[str, Any]] = manager.active_rules()

    if cache is not None:
        cache[key] = rules

    return rules


def run_field_rules(user: CmdbUser, before: dict[str, Any] | None, after: dict[str, Any],
                    type_fields: list[dict[str, Any]], mds_names: Collection[str]) -> RuleApplication:
    """
    Applies the active rules to one object write - after the write check, before the validation of the final state

    Args:
        user (CmdbUser): The writing user
        before (dict[str, Any] | None): The stored object; None for a create
        after (dict[str, Any]): The object as it would be stored - the rules' values are written into it
        type_fields (list[dict[str, Any]]): The object's Type's field definitions
        mds_names (Collection[str]): Its fields in multi-data sections

    Raises:
        FieldRulesManagerGetError | ScopeResolutionError: When a read fails

    Returns:
        RuleApplication: What the rules changed, and the problems when a value would be invalid
    """
    covering: list[Any] = rules_on_type(load_active_rules(user), after.get(CmdbObjectKey.TYPE_ID.value))

    if not covering:
        return RuleApplication()

    person_id: int | None = None

    if any(value == RuleToken.USER_PERSON.value for rule in covering
           for value in (rule.get(FieldRuleKey.SET.value) or {}).values()):
        objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
        person_ids: tuple[int, ...] = ScopeResolver(objects).resolve(user, ScopeReferences(True, False)).person_ids
        person_id = person_ids[0] if person_ids else None

    return apply_rules(covering, before, after, type_fields, mds_names, datetime.now(timezone.utc), person_id)
