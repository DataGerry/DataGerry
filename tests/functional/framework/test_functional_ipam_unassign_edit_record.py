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
What the two IPAM unassign routes leave behind on the objects they edit, over the wire

Both unassign writes are a user's direct edit of the objects they touch, so each written object gets
what the REST object update gives an edit: its version bumped and its edit stamp set in the stored
document, one EDIT change-log entry carrying the route's comment and the new version, and one UPDATE
webhook with the before and after states. Pinned here through the real routes, the real Flask stack
and the real database; the webhook dispatch is replaced by a recorder, since the delivery itself is
the webhook module's concern.

Also pinned: a request refused before the write leaves no entry and fires no webhook, and a log
write that fails does not fail the unassign - the lost entry is reported under the marker instead
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.logs_manager import LogsManager
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_LOST_MARKER, ObjectLogKey
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpamSection,
    IpAddressFamily,
)
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectLogComment
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUBNET_OVERVIEW_URL: str = '/ipam/subnet/overview'
SUPERNET_OVERVIEW_URL: str = '/ipam/supernet/overview'
SIDE_EFFECTS_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper'

SUPERNET_TYPE_ID: int = 9810
SUBNET_TYPE_ID: int = 9811
CARRIER_TYPE_ID: int = 9812

SUPERNET_ID: int = 9820
SUBNET_ID: int = 9821
CARRIER_ID: int = 9822
UNSEEDED_ID: int = 9899

SUBNET_RANGE: str = '10.81.0.0/16'
CARRIER_IP: str = '10.81.0.5'

ADMIN_ID: int = 1
START_VERSION: str = '1.0.0'
PATCHED_VERSION: str = '1.0.1'

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUPERNET_ID, SUBNET_ID, CARRIER_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the IPAM feature so the gated /ipam routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


@pytest.fixture(name='webhooks')
def fixture_webhooks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records every webhook the side-effect helper dispatches, instead of delivering it."""
    sent: list[dict[str, Any]] = []

    def _record(_user: Any, operation: WebhookEventType, object_before: Any = None, object_after: Any = None,
                changes: Any = None) -> None:
        sent.append({'operation': operation, 'before': object_before, 'after': object_after, 'changes': changes})

    monkeypatch.setattr(f'{SIDE_EFFECTS_PATH}.send_webhook_event', _record)

    return sent


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A supernet, one subnet assigned to it, and a carrier with one interface row in that subnet."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'fn-edit-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'fn-edit-subnet', SpecialType.SUBNET),
        make_type_doc(CARRIER_TYPE_ID, 'fn-edit-carrier', None),
    ])
    objects.insert_many([
        make_object_doc(SUPERNET_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'fn-edit-sn'),
            make_field(SupernetField.TYPE, IpAddressFamily.IPV4),
            make_field(SupernetField.NETWORK_RANGE, '10.80.0.0/12'),
        ]),
        make_object_doc(SUBNET_ID, SUBNET_TYPE_ID, [
            make_field(SubnetField.NAME, 'fn-edit-sub'),
            make_field(SubnetField.TYPE, IpAddressFamily.IPV4),
            make_field(SubnetField.NETWORK_RANGE, SUBNET_RANGE),
            make_field(SubnetField.PARENT_SUPERNET, SUPERNET_ID),
        ]),
        make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [make_field('dg-name', 'fn-edit-host')], mds=[{
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
            CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
                make_field(InterfaceField.SUBNET, SUBNET_ID),
                make_field(InterfaceField.IP, CARRIER_IP),
                make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
            ]}],
        }]),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': OBJECT_IDS}})
    logs.delete_many({ObjectLogKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})


@pytest.fixture(name='logs')
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The change-log collection."""
    return database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """The objects collection."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _edit_entries(logs, object_id: int) -> list[dict[str, Any]]:
    """Every EDIT entry of one object."""
    return list(logs.find({ObjectLogKey.OBJECT_ID.value: object_id, 'action': LogAction.EDIT.value}))


def _detach_subnet(rest_api, subnet_id: int = SUBNET_ID):
    """POST the supernet detach of one subnet."""
    return rest_api.post(f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/unassign', json={'subnet_ids': [subnet_id]})


def _unassign_ip(rest_api, ip: str = CARRIER_IP):
    """POST the subnet-side unassign of one IP."""
    return rest_api.post(f'{SUBNET_OVERVIEW_URL}/{SUBNET_ID}/unassign', json={'ips': [ip]})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 supernet detach                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSupernetDetach:
    """POST /ipam/supernet/overview/<id>/subnets/unassign"""

    def test_the_stored_subnet_is_bumped_and_stamped(self, rest_api, objects) -> None:
        """The version and edit stamp are stored with the cleared reference."""
        assert _detach_subnet(rest_api).status_code == HTTPStatus.OK

        stored = objects.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_ID})
        assert stored[CmdbObjectKey.VERSION] == PATCHED_VERSION
        assert stored[CmdbObjectKey.EDITOR_ID] == ADMIN_ID
        assert stored[CmdbObjectKey.LAST_EDIT_TIME] is not None

    def test_one_edit_entry_carries_the_comment_and_the_new_version(self, rest_api, logs) -> None:
        """The change log shows the detach, as the version it produced."""
        _detach_subnet(rest_api)

        entries = _edit_entries(logs, SUBNET_ID)
        assert len(entries) == 1
        assert entries[0][ObjectLogKey.COMMENT.value] == ObjectLogComment.SUBNET_UNASSIGNED_FROM_SUPERNET.value
        assert entries[0][ObjectLogKey.VERSION.value] == PATCHED_VERSION
        assert entries[0][ObjectLogKey.USER_ID.value] == ADMIN_ID

    def test_one_update_webhook_carries_before_and_after(self, rest_api, webhooks) -> None:
        """The webhook sees the SUBNET assigned before and detached after."""
        _detach_subnet(rest_api)

        assert [hook['operation'] for hook in webhooks] == [WebhookEventType.UPDATE]
        assert webhooks[0]['before'][CmdbObjectKey.VERSION.value] == START_VERSION
        assert webhooks[0]['after'][CmdbObjectKey.VERSION.value] == PATCHED_VERSION

    def test_a_refused_detach_records_nothing(self, rest_api, logs, webhooks, objects) -> None:
        """A 400 before the write leaves the SUBNET, the log and the webhooks untouched."""
        response = rest_api.post(
            f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/unassign', json={'subnet_ids': [SUBNET_ID, UNSEEDED_ID]},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not _edit_entries(logs, SUBNET_ID)
        assert not webhooks
        assert objects.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_ID})[CmdbObjectKey.VERSION] == START_VERSION

    def test_a_failing_log_write_does_not_fail_the_detach(
        self, rest_api, logs, objects, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The detach is stored and answered as usual; the lost entry is reported under the marker."""
        def _failing_insert(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError('logs collection down')

        monkeypatch.setattr(LogsManager, 'insert_log', _failing_insert)

        assert _detach_subnet(rest_api).status_code == HTTPStatus.OK
        assert objects.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_ID})[CmdbObjectKey.VERSION] == PATCHED_VERSION
        assert not _edit_entries(logs, SUBNET_ID)
        assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id={SUBNET_ID}' in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                                SUBNET-side unassign                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSubnetUnassign:
    """POST /ipam/subnet/overview/<id>/unassign"""

    def test_the_stored_owner_is_bumped_and_stamped(self, rest_api, objects) -> None:
        """The owner carrying the interface row gets the version and edit stamp."""
        assert _unassign_ip(rest_api).status_code == HTTPStatus.OK

        stored = objects.find_one({CmdbObjectKey.PUBLIC_ID: CARRIER_ID})
        assert stored[CmdbObjectKey.VERSION] == PATCHED_VERSION
        assert stored[CmdbObjectKey.EDITOR_ID] == ADMIN_ID

    def test_one_edit_entry_carries_the_comment_and_the_new_version(self, rest_api, logs) -> None:
        """The owner's change log shows the unassign."""
        _unassign_ip(rest_api)

        entries = _edit_entries(logs, CARRIER_ID)
        assert len(entries) == 1
        assert entries[0][ObjectLogKey.COMMENT.value] == ObjectLogComment.IPS_UNASSIGNED_FROM_SUBNET.value
        assert entries[0][ObjectLogKey.VERSION.value] == PATCHED_VERSION

    def test_one_update_webhook_carries_before_and_after(self, rest_api, webhooks) -> None:
        """The webhook sees the owner before and after its row was detached."""
        _unassign_ip(rest_api)

        assert [hook['operation'] for hook in webhooks] == [WebhookEventType.UPDATE]
        assert webhooks[0]['before'][CmdbObjectKey.VERSION.value] == START_VERSION
        assert webhooks[0]['after'][CmdbObjectKey.VERSION.value] == PATCHED_VERSION

    def test_a_refused_unassign_records_nothing(self, rest_api, logs, webhooks) -> None:
        """An IP not assigned in the subnet is a 400 before any owner is written."""
        assert _unassign_ip(rest_api, ip='10.81.0.99').status_code == HTTPStatus.BAD_REQUEST
        assert not _edit_entries(logs, CARRIER_ID)
        assert not webhooks
