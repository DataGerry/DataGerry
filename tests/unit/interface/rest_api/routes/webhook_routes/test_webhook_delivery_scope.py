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
Unit tests for cmdb.interface.rest_api.routes.webhook_routes.webhook_delivery_scope

A webhook receives the write of an object only when its owner exists, is active and may READ the object's type.
Each refusal is checked against a twin that passes, so a test cannot pass because everything is refused
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.interface.rest_api.routes.webhook_routes.webhook_delivery_scope import (
    OBJECT_TYPE_ID_KEY,
    event_type_id,
    owner_may_receive,
    scope_webhooks_to_owners,
)
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

READER_GROUP_ID: int = 2
OTHER_GROUP_ID: int = 9
TYPE_BEFORE_ID: int = 11
TYPE_AFTER_ID: int = 12
OWNER_ID: int = 31
OTHER_OWNER_ID: int = 32


def _owner(group_id: int = READER_GROUP_ID, active: bool = True) -> Any:
    """A stand-in CmdbUser: the scope reads only active and group_id"""
    return SimpleNamespace(group_id=group_id, active=active)


def _type_readable_by(group_id: int) -> dict[str, Any]:
    """A CmdbType document whose activated ACL lets one group READ"""
    return {'acl': {'activated': True, 'groups': {'includes': {str(group_id): ['READ']}}}}


def _webhook(public_id: int, owner_id: int | None) -> Any:
    """A stand-in CmdbWebhook"""
    return SimpleNamespace(public_id=public_id, owner_id=owner_id)


def test_the_type_key_is_the_object_documents_key() -> None:
    """The scope reads the type the way the object document spells it"""
    assert OBJECT_TYPE_ID_KEY in CmdbObject.SCHEMA

# ---------------------------------------------------- event_type_id ------------------------------------------------- #

class TestEventTypeId:
    """The state after the change names the type; the state before is the fallback"""

    def test_the_state_after_wins(self) -> None:
        """An update carries both; the type the object has now decides"""
        assert event_type_id({'type_id': TYPE_BEFORE_ID}, {'type_id': TYPE_AFTER_ID}) == TYPE_AFTER_ID

    def test_a_delete_falls_back_to_the_state_before(self) -> None:
        """A delete has no state after"""
        assert event_type_id({'type_id': TYPE_BEFORE_ID}, None) == TYPE_BEFORE_ID

    def test_a_create_reads_the_state_after(self) -> None:
        """A create has no state before"""
        assert event_type_id(None, {'type_id': TYPE_AFTER_ID}) == TYPE_AFTER_ID

    @pytest.mark.parametrize('before, after', [
        (None, None), ({}, {}), ({'type_id': '11'}, {'type_id': None}),
    ], ids=['nothing', 'no-key', 'not-an-int'])
    def test_no_usable_type_id_is_none(self, before: Any, after: Any) -> None:
        """Nothing to read: the scope then treats the type as readable"""
        assert event_type_id(before, after) is None

    def test_a_state_after_without_a_type_falls_back(self) -> None:
        """Only a usable value wins"""
        assert event_type_id({'type_id': TYPE_BEFORE_ID}, {'type_id': None}) == TYPE_BEFORE_ID

# -------------------------------------------------- owner_may_receive ----------------------------------------------- #

class TestOwnerMayReceive:
    """Exists, active, may READ the type"""

    def test_a_reader_receives(self) -> None:
        """The twin every refusal below is measured against"""
        assert owner_may_receive(_owner(), _type_readable_by(READER_GROUP_ID)) is True

    def test_no_owner_receives_nothing(self) -> None:
        """A deleted or never-recorded owner"""
        assert owner_may_receive(None, _type_readable_by(READER_GROUP_ID)) is False

    def test_a_deactivated_owner_receives_nothing(self) -> None:
        """Even of a type the owner's group may read"""
        assert owner_may_receive(_owner(active=False), _type_readable_by(READER_GROUP_ID)) is False

    def test_a_deactivated_owner_receives_nothing_without_a_type(self) -> None:
        """Activity is checked before the type"""
        assert owner_may_receive(_owner(active=False), None) is False

    def test_an_owner_whose_group_may_not_read_receives_nothing(self) -> None:
        """The type ACL the object read applies"""
        assert owner_may_receive(_owner(group_id=OTHER_GROUP_ID), _type_readable_by(READER_GROUP_ID)) is False

    def test_a_type_that_cannot_be_read_back_is_not_refused(self) -> None:
        """A deleted type: the rule the type ACL stage applies everywhere"""
        assert owner_may_receive(_owner(group_id=OTHER_GROUP_ID), None) is True

    @pytest.mark.parametrize('type_document', [{}, {'acl': {'activated': False}}], ids=['no-acl', 'inactive-acl'])
    def test_a_type_without_an_active_acl_is_readable(self, type_document: dict[str, Any]) -> None:
        """The ACL is opt-in"""
        assert owner_may_receive(_owner(group_id=OTHER_GROUP_ID), type_document) is True

# ----------------------------------------------- scope_webhooks_to_owners ------------------------------------------- #

class TestScopeWebhooksToOwners:
    """Each webhook is judged by its own owner"""

    def test_keeps_the_webhooks_whose_owner_may_read_in_order(self) -> None:
        """Two owners, two groups: only the reader's webhooks stay"""
        webhooks = [_webhook(1, OWNER_ID), _webhook(2, OTHER_OWNER_ID), _webhook(3, OWNER_ID)]
        owners = {OWNER_ID: _owner(), OTHER_OWNER_ID: _owner(group_id=OTHER_GROUP_ID)}

        kept = scope_webhooks_to_owners(webhooks, _type_readable_by(READER_GROUP_ID), owners)

        assert [webhook.public_id for webhook in kept] == [1, 3]

    def test_the_other_owner_is_the_reader_the_other_way_round(self) -> None:
        """Swapping the groups swaps the result: the owner lookup is keyed, not positional"""
        webhooks = [_webhook(1, OWNER_ID), _webhook(2, OTHER_OWNER_ID)]
        owners = {OWNER_ID: _owner(group_id=OTHER_GROUP_ID), OTHER_OWNER_ID: _owner()}

        kept = scope_webhooks_to_owners(webhooks, _type_readable_by(READER_GROUP_ID), owners)

        assert [webhook.public_id for webhook in kept] == [2]

    def test_an_owner_missing_from_the_lookup_receives_nothing(self) -> None:
        """A deleted user"""
        kept = scope_webhooks_to_owners([_webhook(1, OWNER_ID)], None, {})

        assert not kept

    @pytest.mark.parametrize('webhook', [_webhook(1, None), SimpleNamespace(public_id=1)], ids=['none', 'no-attribute'])
    def test_an_ownerless_webhook_receives_nothing(self, webhook: Any) -> None:
        """Never recorded - even though another webhook's owner may read"""
        kept = scope_webhooks_to_owners([webhook], None, {OWNER_ID: _owner()})

        assert not kept
