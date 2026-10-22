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
Unit tests for types_update_helper - the three steps of the Type update

Every rule a step runs is patched at the helper's path (each has tests of its own), so what is pinned here is the
step itself: which rules it runs, in which order, with which arguments, and that a refusal stops the rest
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.errors.manager.types_manager import TypesManagerAlignmentError, TypesManagerUpdateError
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.type_model import TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    SPECIAL_TYPE_IMMUTABLE_MESSAGE,
    TYPE_GONE_BEFORE_UPDATE_MESSAGE,
    TypeAlignmentStep,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_update_helper import (
    guard_type_update_changes,
    prepare_type_update_payload,
    write_type_update,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_update_helper'

TYPE_PUBLIC_ID: int = 7
STORED_SPECIAL_TYPE: str = 'STORED'
REQUESTED_SPECIAL_TYPE: str = 'REQUESTED'
REQUESTED_USES_PORTS: bool = True
STORED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'2': ['READ']}}}
DROPPED_CLAIMS: list[str] = ['dg-gone']
REMOVED_TEMPLATES: tuple[set[str], dict[str, tuple[list[str], str]]] = ({'dg-removed'}, {})
STRIPPED_DOCUMENT_KEY: str = 'stripped'
HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

# The rules prepare_type_update_payload runs, in its order
PAYLOAD_RULES: list[str] = [
    'enforce_special_type_license',
    'enforce_rack_selectable_as_parent',
    'enforce_uses_ports_license',
    'reconcile_global_template_copies',
    'normalize_port_section_index',
    'normalize_ci_explorer_label',
    'drop_stale_type_references',
    'guard_new_identifiers',
    'guard_type_structure',
    'guard_field_patterns',
    'guard_field_defaults',
    'abort_if_unknown_acl_groups',
]

# The guards guard_type_update_changes runs after the SpecialType check, in its order
CHANGE_GUARDS: list[str] = [
    'guard_field_identifier_change',
    'guard_mds_section_identifier_change',
    'guard_location_field_removal',
    'guard_referenced_section_removal',
    'guard_selectable_as_parent_change',
    'guard_uses_ports_change',
]


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A bare app for the request context abort() needs"""
    return Flask(__name__)


def _patched(names: list[str]) -> tuple[MagicMock, list[Any]]:
    """Patches each named rule at the helper's path under one parent mock, so their call order is recorded"""
    parent = MagicMock()
    patchers = [patch(f'{HELPER_PATH}.{name}', getattr(parent, name)) for name in names]

    for patcher in patchers:
        patcher.start()

    return parent, patchers


def _stop(patchers: list[Any]) -> None:
    """Undoes _patched"""
    for patcher in patchers:
        patcher.stop()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             prepare_type_update_payload                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPrepareTypeUpdatePayload:
    """The payload's rules, in order, judged against the stored Type"""

    @pytest.fixture(name='rules')
    def fixture_rules(self) -> Any:
        """Every rule patched; the groups manager and the stored acl stubbed"""
        parent, patchers = _patched(PAYLOAD_RULES)
        parent.reconcile_global_template_copies.return_value = DROPPED_CLAIMS

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager') as get_manager, \
             patch(f'{HELPER_PATH}.CmdbType.to_json', return_value={TypeSchemaKey.ACL.value: STORED_ACL}):
            parent.get_manager = get_manager
            yield parent

        _stop(patchers)

    def test_every_rule_runs_in_order_with_its_arguments(self, rules: MagicMock) -> None:
        """Licences first, the templates before any rule judges the payload, the acl groups last"""
        user = MagicMock()
        old_type = SimpleNamespace(special_type=STORED_SPECIAL_TYPE)
        data: dict[str, Any] = {
            TypeSchemaKey.SPECIAL_TYPE.value: REQUESTED_SPECIAL_TYPE,
            TypeSchemaKey.USES_PORTS.value: REQUESTED_USES_PORTS,
        }

        assert prepare_type_update_payload(data, old_type, user) == DROPPED_CLAIMS

        groups_manager = rules.get_manager.return_value
        assert [entry for entry in rules.mock_calls if entry[0] in PAYLOAD_RULES] == [
            call.enforce_special_type_license(user, STORED_SPECIAL_TYPE, REQUESTED_SPECIAL_TYPE),
            call.enforce_rack_selectable_as_parent(STORED_SPECIAL_TYPE, data),
            call.enforce_uses_ports_license(user, REQUESTED_USES_PORTS),
            call.reconcile_global_template_copies(data, user),
            call.normalize_port_section_index(data),
            call.normalize_ci_explorer_label(data, old_type),
            call.drop_stale_type_references(data, old_type),
            call.guard_new_identifiers(data, old_type),
            call.guard_type_structure(data),
            call.guard_field_patterns(data, old_type),
            call.guard_field_defaults(data),
            call.abort_if_unknown_acl_groups(data, groups_manager, STORED_ACL),
        ]
        rules.get_manager.assert_called_once_with(ManagerType.GROUPS, user)

    @pytest.mark.parametrize('refusing_rule', PAYLOAD_RULES)
    def test_a_refusal_stops_the_rules_after_it(self, rules: MagicMock, refusing_rule: str) -> None:
        """Nothing after the refusing rule runs"""
        getattr(rules, refusing_rule).side_effect = BadRequest()

        with pytest.raises(BadRequest):
            prepare_type_update_payload({}, SimpleNamespace(special_type=None), MagicMock())

        later: list[str] = PAYLOAD_RULES[PAYLOAD_RULES.index(refusing_rule) + 1:]
        assert not [entry for entry in rules.mock_calls if entry[0] in later]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_type_update_changes                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardTypeUpdateChanges:
    """The SpecialType first, then every change guard, in order"""

    @pytest.fixture(name='guards')
    def fixture_guards(self) -> Any:
        """Every change guard patched"""
        parent, patchers = _patched(CHANGE_GUARDS)
        yield parent
        _stop(patchers)

    def test_every_guard_runs_in_order_on_both_types(self, guards: MagicMock) -> None:
        """The stored and the new Type, as the caller"""
        user, old_type, new_type = MagicMock(), SimpleNamespace(special_type=STORED_SPECIAL_TYPE), MagicMock()

        guard_type_update_changes(user, old_type, new_type, STORED_SPECIAL_TYPE)

        assert guards.mock_calls == [getattr(call, name)(user, old_type, new_type) for name in CHANGE_GUARDS]

    def test_a_changed_special_type_is_refused_before_any_guard(self, flask_app: Flask, guards: MagicMock) -> None:
        """400 with its message; no guard reads anything"""
        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            guard_type_update_changes(
                MagicMock(), SimpleNamespace(special_type=STORED_SPECIAL_TYPE), MagicMock(), REQUESTED_SPECIAL_TYPE,
            )

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert exc_info.value.description == SPECIAL_TYPE_IMMUTABLE_MESSAGE
        assert not guards.mock_calls

    def test_no_special_type_on_either_side_passes(self, guards: MagicMock) -> None:
        """None == None"""
        guard_type_update_changes(MagicMock(), SimpleNamespace(special_type=None), MagicMock(), None)

        assert len(guards.mock_calls) == len(CHANGE_GUARDS)

    @pytest.mark.parametrize('refusing_guard', CHANGE_GUARDS)
    def test_a_refusal_stops_the_guards_after_it(self, guards: MagicMock, refusing_guard: str) -> None:
        """Nothing after the refusing guard runs"""
        getattr(guards, refusing_guard).side_effect = BadRequest()

        with pytest.raises(BadRequest):
            guard_type_update_changes(MagicMock(), SimpleNamespace(special_type=None), MagicMock(), None)

        assert [entry[0] for entry in guards.mock_calls] == CHANGE_GUARDS[:CHANGE_GUARDS.index(refusing_guard) + 1]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  write_type_update                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWriteTypeUpdate:
    """One write with the marker set, then the alignment of what follows the Type"""

    @pytest.fixture(name='steps')
    def fixture_steps(self) -> Any:
        """The template strip, the CmdbType conversions and the side effects patched"""
        with patch(f'{HELPER_PATH}.strip_removed_global_templates',
                   side_effect=lambda document, _removed: {**document, STRIPPED_DOCUMENT_KEY: True}) as strip, \
             patch(f'{HELPER_PATH}.CmdbType') as cmdb_type, \
             patch(f'{HELPER_PATH}.apply_type_update_side_effects') as side_effects:
            cmdb_type.to_json.return_value = {TypeSchemaKey.PUBLIC_ID.value: TYPE_PUBLIC_ID}
            yield SimpleNamespace(strip=strip, cmdb_type=cmdb_type, side_effects=side_effects)

    @staticmethod
    def _new_type() -> MagicMock:
        """The Type the update writes"""
        new_type = MagicMock()
        new_type.get_public_id.return_value = TYPE_PUBLIC_ID

        return new_type

    def test_the_stripped_document_is_written_with_the_marker(self, steps: SimpleNamespace) -> None:
        """The removed templates are out of it and alignment_pending is set, in the ONE write"""
        types_manager = MagicMock()
        new_type = self._new_type()

        write_type_update(MagicMock(), types_manager, MagicMock(), new_type, REMOVED_TEMPLATES)

        steps.strip.assert_called_once_with(steps.cmdb_type.to_json.return_value, REMOVED_TEMPLATES)
        steps.cmdb_type.to_json.assert_called_once_with(new_type)
        types_manager.update_type.assert_called_once_with(TYPE_PUBLIC_ID, {
            TypeSchemaKey.PUBLIC_ID.value: TYPE_PUBLIC_ID,
            STRIPPED_DOCUMENT_KEY: True,
            TypeSchemaKey.ALIGNMENT_PENDING.value: True,
        })

    def test_the_side_effects_get_the_written_type(self, steps: SimpleNamespace) -> None:
        """What was just written, built from the written document - no read back"""
        user, types_manager, old_type = MagicMock(), MagicMock(), MagicMock()

        write_type_update(user, types_manager, old_type, self._new_type(), REMOVED_TEMPLATES)

        written_document = types_manager.update_type.call_args.args[1]
        steps.cmdb_type.from_data.assert_called_once_with(written_document)
        steps.side_effects.assert_called_once_with(
            user, types_manager, old_type, steps.cmdb_type.from_data.return_value,
        )
        types_manager.get_type.assert_not_called()

    def test_a_type_gone_before_the_write_is_a_404_without_side_effects(
        self, flask_app: Flask, steps: SimpleNamespace,
    ) -> None:
        """Nothing matched: nothing is aligned to a Type that no longer exists"""
        types_manager = MagicMock()
        types_manager.update_type.return_value = SimpleNamespace(matched_count=0)

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            write_type_update(MagicMock(), types_manager, MagicMock(), self._new_type(), REMOVED_TEMPLATES)

        assert exc_info.value.code == HTTP_NOT_FOUND
        assert exc_info.value.description == TYPE_GONE_BEFORE_UPDATE_MESSAGE.format(public_id=TYPE_PUBLIC_ID)
        steps.side_effects.assert_not_called()

    def test_a_failed_write_aligns_nothing(self, steps: SimpleNamespace) -> None:
        """The write's error reaches the route's table"""
        types_manager = MagicMock()
        types_manager.update_type.side_effect = TypesManagerUpdateError('boom')

        with pytest.raises(TypesManagerUpdateError):
            write_type_update(MagicMock(), types_manager, MagicMock(), self._new_type(), REMOVED_TEMPLATES)

        steps.side_effects.assert_not_called()

    def test_a_failed_alignment_step_passes_through(self, steps: SimpleNamespace) -> None:
        """The Type IS written; the route answers the named step"""
        steps.side_effects.side_effect = TypesManagerAlignmentError('boom', TypeAlignmentStep.LOCATIONS.value)

        with pytest.raises(TypesManagerAlignmentError):
            write_type_update(MagicMock(), MagicMock(), MagicMock(), self._new_type(), REMOVED_TEMPLATES)
