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
Unit tests for the ``acl`` rule of cmdb.class_schema.type_model.cmdb_type_schema

Pure Cerberus tests against the type WRITE schema, the one the routes validate with (``purge_unknown``). Pinned:
every shape the frontend and the create path's completion rely on is accepted - a partial block, a null
``groups`` / ``includes``, a group granted nothing - and every shape the model cannot build or would store
scrambled is refused: a ``groups`` / ``includes`` that is no object, a key that is no group id, a permission list
sent as a string, an unknown permission, a non-boolean ``activated``
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.type_model.cmdb_type_schema import get_type_acl_schema
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

ACL_KEY: str = TypeSchemaKey.ACL.value
ALL_PERMISSIONS: list[str] = [permission.value for permission in AccessControlPermission]


def _acl_errors(acl: Any) -> Any:
    """The errors the ``acl`` key raises under the type write schema; the other keys' errors are ignored"""
    validator = Validator(build_write_schema(CmdbType.SCHEMA), purge_unknown=True)
    validator.validate({ACL_KEY: acl})

    return validator.errors.get(ACL_KEY)


def test_the_type_schema_uses_the_shared_rule() -> None:
    """One declaration, so the route and the import cannot drift apart"""
    assert CmdbType.SCHEMA[ACL_KEY] == get_type_acl_schema()


@pytest.mark.parametrize('acl', [
    {'activated': False, 'groups': {'includes': {}}},
    {'activated': True, 'groups': {'includes': {'1': ['READ'], '12': ALL_PERMISSIONS}}},
    {'activated': False},
    {'groups': {'includes': {'1': ['READ']}}},
    {'activated': False, 'groups': None},
    {'activated': False, 'groups': {'includes': None}},
    {'activated': True, 'groups': {'includes': {'2': []}}},
    {},
], ids=['empty-includes', 'grants', 'flag-only', 'groups-only', 'null-groups', 'null-includes',
        'granted-nothing', 'empty-block'])
def test_the_shapes_in_use_are_accepted(acl: dict[str, Any]) -> None:
    """What the type builder sends, and every partial shape the create path completes"""
    assert _acl_errors(acl) is None


@pytest.mark.parametrize('acl, failing_path', [
    ({'groups': 42}, 'groups'),
    ({'groups': {'includes': [1]}}, 'groups'),
    ({'groups': {'includes': {'abc': ['READ']}}}, 'groups'),
    ({'groups': {'includes': {'0': ['READ']}}}, 'groups'),
    ({'groups': {'includes': {'1': 'READ,UPDATE'}}}, 'groups'),
    ({'groups': {'includes': {'1': ['read']}}}, 'groups'),
    ({'groups': {'includes': {'1': ['READ', 'EXECUTE']}}}, 'groups'),
    ({'activated': 'yes'}, 'activated'),
    ({'activated': 0}, 'activated'),
    ({'activated': None}, 'activated'),
], ids=['groups-no-object', 'includes-no-object', 'key-no-id', 'key-zero', 'permissions-as-string',
        'lower-case-permission', 'unknown-permission', 'flag-string', 'flag-zero', 'flag-null'])
def test_a_malformed_block_is_refused(acl: dict[str, Any], failing_path: str) -> None:
    """Each of these would crash the model or be stored in a form no access check can read"""
    errors = _acl_errors(acl)

    assert errors
    assert failing_path in errors[0]


def test_an_acl_that_is_no_object_is_refused() -> None:
    """The block itself, too"""
    assert _acl_errors(['READ'])


def test_an_unknown_key_inside_the_block_is_purged() -> None:
    """Dropped, not refused - what the model does with it as well"""
    validator = Validator(build_write_schema(CmdbType.SCHEMA), purge_unknown=True)
    validator.validate({ACL_KEY: {'activated': False, 'whatever': [1]}})

    assert validator.errors.get(ACL_KEY) is None
    assert validator.document[ACL_KEY] == {'activated': False}
