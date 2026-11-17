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
Functional tests: a person selector in an object's summary line shows only the persons the reader may see

Seeds a visible person type (Ada) and one only the admin group may READ (Eve), an asset type whose summary is
``[name, owner]`` with ``owner`` a multiple person selector, two assets (owned by Ada + Eve / by Eve only) each with
one IPAM interface row in a seeded subnet, a port on each asset, a rack holding both, ISMS assessments and
assignments of both, and a ticket type whose ``ref`` field points at an asset. A reader whose group holds the view
rights of every area reads them, and so does the admin. Pinned on every surface, for both readers:

  - the shared asset's line ends ``srv-x | Ada`` for the reader and ``srv-x | Ada, Eve`` for the admin
  - the Eve-only asset's line ends ``srv-y`` for the reader - no separator, no text - and ``srv-y | Eve`` for the admin
  - no person id is ever written into a line

Surfaces: the IPAM subnet overview's assigned rows and the IPAM picker, the rack overview, the port's assignable
interface picker, the ISMS RiskAssessment list naming, the ControlMeasureAssignment list and the risk assessments
report, and the CI Explorer's flattened reference value
"""
import json
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRisk, IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKey, RackMountKind
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpAddressFamily,
    IpamPagination,
    IpamRowStatus,
    IpamSection,
    SubnetField,
)
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerRight
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_constants import IpamRight
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRight
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackRight
# -------------------------------------------------------------------------------------------------------------------- #

SUBNET_OVERVIEW_URL: str = '/ipam/subnet/overview'
IPAM_PICKER_URL: str = '/ipam/assignable-objects/'
RACKS_URL: str = '/racks'
PORTS_URL: str = '/ports'
RISK_ASSESSMENTS_URL: str = '/isms/risk_assessments/'
ASSIGNMENTS_URL: str = '/isms/control_measure_assignments/'
RA_REPORT_URL: str = '/isms/reports/risk_assessments'
CI_EXPLORER_URL: str = '/ci_explorer/items'

PERSON_TYPE: int = 48801
HIDDEN_TYPE: int = 48802
ASSET_TYPE: int = 48803
TICKET_TYPE: int = 48804
RACK_TYPE: int = 48805
SUBNET_TYPE: int = 48806
TYPE_IDS: list[int] = [PERSON_TYPE, HIDDEN_TYPE, ASSET_TYPE, TICKET_TYPE, RACK_TYPE, SUBNET_TYPE]

ADA: int = 48811
EVE: int = 48812
SHARED_ASSET: int = 48821
EVE_ASSET: int = 48822
ASSETS: list[int] = [SHARED_ASSET, EVE_ASSET]
SHARED_TICKET: int = 48831
EVE_TICKET: int = 48832
RACK: int = 48841
SUBNET: int = 48851
OBJECT_IDS: list[int] = [ADA, EVE, SHARED_ASSET, EVE_ASSET, SHARED_TICKET, EVE_TICKET, RACK, SUBNET]

# One port per asset, one mount per asset
PORTS: dict[int, int] = {SHARED_ASSET: 48861, EVE_ASSET: 48862}
MOUNTS: dict[int, int] = {SHARED_ASSET: 48871, EVE_ASSET: 48872}

RISK: int = 48881
CONTROL_MEASURE: int = 48882
ASSESSMENTS: dict[int, int] = {SHARED_ASSET: 48883, EVE_ASSET: 48884}
CMAS: dict[int, int] = {SHARED_ASSET: 48885, EVE_ASSET: 48886}

READER_GROUP: int = 48891
READER: int = 48892
READER_NAME: str = 'fn-sumline-reader'
ISMS_VIEW_RIGHTS: list[str] = [
    'base.isms.report.view', 'base.isms.riskAssessment.view', 'base.isms.controlMeasureAssignment.view',
]
READER_RIGHTS: list[str] = [right.value for right in ObjectRightName] + ISMS_VIEW_RIGHTS + [
    CiExplorerRight.VIEW.value, IpamRight.VIEW.value, RackRight.VIEW.value, PortRight.VIEW.value,
]

NAME: str = 'name'
OWNER: str = 'owner'
LABEL_FIELD: str = 'display_name'
ASSET_FIELD: str = 'asset'
SHARED_NAME: str = 'srv-x'
EVE_NAME: str = 'srv-y'
NAME_SEARCH: str = 'srv-'
ASSET_LABEL: str = 'Fn-Sumline-Asset'
ADMIN_PERMISSIONS: list[str] = ['CREATE', 'READ', 'UPDATE', 'DELETE']

SUBNET_RANGE: str = '10.86.0.0/24'
ASSET_IPS: dict[int, str] = {SHARED_ASSET: '10.86.0.5', EVE_ASSET: '10.86.0.6'}
ASSET_MACS: dict[int, str] = {SHARED_ASSET: '00:86:00:00:00:05', EVE_ASSET: '00:86:00:00:00:06'}
INTERFACE_ROW_ID: int = 1
RACK_HEIGHT: int = 42
RACK_NAME: str = 'fn-sumline-rack'
PORT_NAME: str = 'Gi0/1'

# The tail of each asset's line, per reader
LINE_TAILS: dict[str, dict[int, str]] = {
    'reader': {SHARED_ASSET: f'{SHARED_NAME} | Ada', EVE_ASSET: EVE_NAME},
    'admin': {SHARED_ASSET: f'{SHARED_NAME} | Ada, Eve', EVE_ASSET: f'{EVE_NAME} | Eve'},
}
READERS: list[str] = list(LINE_TAILS)
# The ControlMeasureAssignment summary closes on the assessed object's type label
CMA_TYPE_SUFFIX: str = f' ({ASSET_LABEL})'


def _type(public_id: int, name: str, fields: list[dict[str, Any]], sections: list[dict[str, Any]],
          marker: str = '', admin_only: bool = False, summary: list[str] | None = None,
          **extra: Any) -> dict[str, Any]:
    """A type document"""
    return {
        'public_id': public_id, 'name': name, 'label': name.title(), 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker, 'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': summary or []}, 'sections': sections,
                        'externals': []},
        'acl': {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ADMIN_PERMISSIONS}}}
        if admin_only else {'activated': False, 'groups': {'includes': None}},
        **extra,
    }


def _section(name: str, fields: list[str]) -> dict[str, Any]:
    """A plain section"""
    return {'type': 'section', 'name': name, 'label': name.title(), 'fields': fields}


def _text(name: str) -> dict[str, Any]:
    """A text field definition"""
    return {'type': 'text', 'name': name, 'label': name.title()}


def _person_type(public_id: int, name: str, admin_only: bool = False) -> dict[str, Any]:
    """A PERSON type labelled by display_name"""
    return _type(public_id, name, [_text(LABEL_FIELD)], [_section('main', [LABEL_FIELD])],
                 marker=SpecialType.PERSON.value, admin_only=admin_only)


def _types() -> list[dict[str, Any]]:
    """The two person types, the asset, ticket, rack and subnet types"""
    asset_fields: list[dict[str, Any]] = [
        _text(NAME),
        {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON'], 'multiple': True},
    ]
    interface_section: dict[str, Any] = {'type': 'multi-data-section', 'name': IpamSection.INTERFACE.value,
                                         'label': 'Interfaces', 'fields': []}
    ticket_fields: list[dict[str, Any]] = [
        {'type': 'ref', 'name': ASSET_FIELD, 'label': 'Asset', 'ref_types': [ASSET_TYPE]},
    ]
    rack_fields: list[dict[str, Any]] = [_text(RackField.NAME.value),
                                         {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height'}]
    subnet_fields: list[dict[str, Any]] = [_text(field.value) for field in
                                           (SubnetField.NAME, SubnetField.TYPE, SubnetField.NETWORK_RANGE)]

    return [
        _person_type(PERSON_TYPE, 'fn-sumline-person'),
        _person_type(HIDDEN_TYPE, 'fn-sumline-hidden', admin_only=True),
        _type(ASSET_TYPE, 'fn-sumline-asset', asset_fields, [_section('main', [NAME, OWNER]), interface_section],
              summary=[NAME, OWNER], uses_ports=True),
        _type(TICKET_TYPE, 'fn-sumline-ticket', ticket_fields, [_section('main', [ASSET_FIELD])]),
        _type(RACK_TYPE, 'fn-sumline-rack', rack_fields, [_section('main', [field['name'] for field in rack_fields])],
              marker=SpecialType.RACK.value, summary=[RackField.NAME.value]),
        _type(SUBNET_TYPE, 'fn-sumline-subnet', subnet_fields,
              [_section('main', [field['name'] for field in subnet_fields])],
              marker=SpecialType.SUBNET.value, summary=[SubnetField.NAME.value]),
    ]


def _object(public_id: int, type_id: int, fields: dict[str, Any],
            sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An object document"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': sections or [],
            'fields': [{'name': name, 'value': value} for name, value in fields.items()]}


def _asset(public_id: int, name: str, owners: list[int]) -> dict[str, Any]:
    """An asset with its owners and one interface row in the subnet"""
    row: dict[str, Any] = {'multi_data_id': INTERFACE_ROW_ID, 'data': [
        {'name': field, 'value': value} for field, value in (
            (InterfaceField.SUBNET.value, SUBNET), (InterfaceField.IP.value, ASSET_IPS[public_id]),
            (InterfaceField.MAC.value, ASSET_MACS[public_id]), (InterfaceField.TYPE.value, IpAddressFamily.IPV4.value),
        )
    ]}

    return _object(public_id, ASSET_TYPE, {NAME: name, OWNER: owners}, [
        {'section_id': IpamSection.INTERFACE.value, 'highest_id': INTERFACE_ROW_ID, 'values': [row]},
    ])


def _seeds() -> dict[str, list[dict[str, Any]]]:
    """Every seeded document, by collection"""
    now: datetime = datetime.now(timezone.utc)

    return {
        CmdbType.COLLECTION: _types(),
        CmdbObject.COLLECTION: [
            _object(ADA, PERSON_TYPE, {LABEL_FIELD: 'Ada'}),
            _object(EVE, HIDDEN_TYPE, {LABEL_FIELD: 'Eve'}),
            _asset(SHARED_ASSET, SHARED_NAME, [ADA, EVE]),
            _asset(EVE_ASSET, EVE_NAME, [EVE]),
            _object(SHARED_TICKET, TICKET_TYPE, {ASSET_FIELD: SHARED_ASSET}),
            _object(EVE_TICKET, TICKET_TYPE, {ASSET_FIELD: EVE_ASSET}),
            _object(RACK, RACK_TYPE, {RackField.NAME.value: RACK_NAME, RackField.HEIGHT.value: RACK_HEIGHT}),
            _object(SUBNET, SUBNET_TYPE, {SubnetField.NAME.value: 'fn-sumline-subnet',
                                          SubnetField.TYPE.value: IpAddressFamily.IPV4.value,
                                          SubnetField.NETWORK_RANGE.value: SUBNET_RANGE}),
        ],
        CmdbPort.COLLECTION: [
            {PortKey.PUBLIC_ID.value: port_id, PortKey.OBJECT_ID.value: asset,
             PortKey.SIDE.value: PortSide.SINGLE.value, PortKey.NAME.value: PORT_NAME, PortKey.AUTHOR_ID.value: 1}
            for asset, port_id in PORTS.items()
        ],
        CmdbRackMount.COLLECTION: [
            {RackMountKey.PUBLIC_ID.value: mount_id, RackMountKey.RACK_ID.value: RACK,
             RackMountKey.OBJECT_ID.value: asset, RackMountKey.KIND.value: RackMountKind.MOUNT.value,
             RackMountKey.AREA.value: RackArea.UNASSIGNED.value, RackMountKey.POSITION.value: position,
             RackMountKey.AUTHOR_ID.value: 1, RackMountKey.CREATION_TIME.value: now}
            for position, (asset, mount_id) in enumerate(MOUNTS.items())
        ],
        IsmsRisk.COLLECTION: [{'public_id': RISK, 'name': 'fn-sumline-risk'}],
        IsmsRiskAssessment.COLLECTION: [
            {'public_id': ra_id, 'risk_id': RISK, 'object_id': asset, 'object_id_ref_type': 'OBJECT'}
            for asset, ra_id in ASSESSMENTS.items()
        ],
        IsmsControlMeasureAssignment.COLLECTION: [
            {'public_id': cma_id, 'control_measure_id': CONTROL_MEASURE, 'risk_assessment_id': ASSESSMENTS[asset]}
            for asset, cma_id in CMAS.items()
        ],
        CmdbUserGroup.COLLECTION: [
            {'public_id': READER_GROUP, 'name': READER_NAME, 'label': READER_NAME, 'rights': READER_RIGHTS},
        ],
        CmdbUser.COLLECTION: [{'public_id': READER, 'user_name': READER_NAME, 'active': True,
                               'group_id': READER_GROUP, 'registration_time': now}],
    }


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses every feature so the gated IPAM, rack, port and ISMS routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Every seeded document; purged before and after"""
    collection = partial(database_manager.get_collection, db_name=database_name)
    seeds: dict[str, list[dict[str, Any]]] = _seeds()

    def _purge() -> None:
        for name, docs in seeds.items():
            collection(name).delete_many({'public_id': {'$in': [doc['public_id'] for doc in docs]}})

    _purge()
    for name, docs in seeds.items():
        collection(name).insert_many(docs)

    yield

    _purge()


def _as(reader: str) -> dict[str, Any]:
    """The request kwargs: the reader, or nothing for the admin the test client sends by default"""
    if reader == 'admin':
        return {}

    return {'user': CmdbUser(public_id=READER, user_name=READER_NAME, active=True, group_id=READER_GROUP)}


def _get(rest_api, url: str, reader: str, **kwargs: Any) -> dict[str, Any]:
    """The JSON answer of a GET, asserted 200"""
    response = rest_api.get(url, **_as(reader), **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_data(as_text=True)

    return response.get_json()


def _assert_lines(lines: dict[int, str], reader: str, with_type: bool = True, suffix: str = '') -> None:
    """Each asset's line ends with what the reader may see of its owners (then ``suffix``), and names no person id"""
    for asset, tail in LINE_TAILS[reader].items():
        expected: str = (f'{ASSET_LABEL} #{asset} - {tail}' if with_type else tail) + suffix

        assert lines[asset].endswith(expected), lines[asset]
        assert str(ADA) not in lines[asset] and str(EVE) not in lines[asset]


def _listed(rest_api, url: str, ids: list[int], reader: str) -> dict[int, dict[str, Any]]:
    """An ISMS list route's entries of the given ids, keyed by public_id"""
    body: dict[str, Any] = _get(rest_api, url, reader,
                                query_string={'limit': 0, 'filter': json.dumps({'public_id': {'$in': ids}})})

    return {entry['public_id']: entry for entry in body['results']}


@pytest.mark.parametrize('reader', READERS)
class TestIpam:
    """The IPAM subnet overview's assigned rows and the IPAM picker"""

    def test_the_assigned_rows_show_the_visible_owners(self, rest_api, reader: str) -> None:
        """GET /ipam/subnet/overview/<subnet>: the summary_line of each assigned interface row"""
        rows: list[dict[str, Any]] = _get(rest_api, f'{SUBNET_OVERVIEW_URL}/{SUBNET}', reader,
                                          query_string={'status': IpamRowStatus.ASSIGNED.value})['ips']['rows']
        by_ip: dict[str, str] = {row['ip']: row['assigned_to']['summary_line'] for row in rows}

        _assert_lines({asset: by_ip[ip] for asset, ip in ASSET_IPS.items()}, reader)

    @pytest.mark.parametrize('search', ['', NAME_SEARCH], ids=['unsearched', 'searched'])
    def test_the_picker_shows_the_visible_owners(self, rest_api, reader: str, search: str) -> None:
        """GET /ipam/assignable-objects/: the summary_line of each asset row, both page paths"""
        query: dict[str, Any] = {'search': search, 'page_size': IpamPagination.MAX_PAGE_SIZE}
        rows: list[dict[str, Any]] = _get(rest_api, IPAM_PICKER_URL, reader, query_string=query)['rows']

        _assert_lines({row['public_id']: row['summary_line'] for row in rows if row['public_id'] in ASSETS}, reader)


@pytest.mark.parametrize('reader', READERS)
class TestRack:
    """GET /racks/<rack>/overview"""

    def test_the_mounted_rows_show_the_visible_owners(self, rest_api, reader: str) -> None:
        """The unassigned bucket's rows carry each asset's line, without the type prefix"""
        rows: list[dict[str, Any]] = _get(rest_api, f'{RACKS_URL}/{RACK}/overview', reader)['areas'][
            RackArea.UNASSIGNED.value]

        _assert_lines({row['object_id']: row['summary_line'] for row in rows}, reader, with_type=False)


@pytest.mark.parametrize('reader', READERS)
class TestPort:
    """GET /ports/<port>/assignable_interfaces/"""

    def test_the_interface_rows_show_the_visible_owners(self, rest_api, reader: str) -> None:
        """Each port's one interface row names its own asset's line in object_info"""
        lines: dict[int, str] = {}

        for asset, port_id in PORTS.items():
            rows: list[dict[str, Any]] = _get(rest_api, f'{PORTS_URL}/{port_id}/assignable_interfaces/',
                                              reader)['rows']
            lines[asset] = rows[0]['object_info']['summary_line']

        _assert_lines(lines, reader)


@pytest.mark.parametrize('reader', READERS)
class TestIsms:
    """The RiskAssessment and ControlMeasureAssignment lists and the risk assessments report"""

    def test_the_risk_assessment_naming_shows_the_visible_owners(self, rest_api, reader: str) -> None:
        """GET /isms/risk_assessments/: naming.object_id_name"""
        listed: dict[int, dict[str, Any]] = _listed(rest_api, RISK_ASSESSMENTS_URL, list(ASSESSMENTS.values()),
                                                    reader)

        _assert_lines({asset: listed[ra_id]['naming']['object_id_name'] for asset, ra_id in ASSESSMENTS.items()},
                      reader)

    def test_the_assignment_summary_shows_the_visible_owners(self, rest_api, reader: str) -> None:
        """GET /isms/control_measure_assignments/: naming.cma_summary ends with the asset's line and its type label"""
        listed: dict[int, dict[str, Any]] = _listed(rest_api, ASSIGNMENTS_URL, list(CMAS.values()), reader)

        _assert_lines({asset: listed[cma_id]['naming']['cma_summary'] for asset, cma_id in CMAS.items()}, reader,
                      suffix=CMA_TYPE_SUFFIX)

    def test_the_report_shows_the_visible_owners(self, rest_api, reader: str) -> None:
        """GET /isms/reports/risk_assessments: the assigned_object column"""
        body: dict[str, Any] = _get(rest_api, RA_REPORT_URL, reader, query_string={
            'limit': 0, 'sort': 'public_id', 'order': 1,
            'filter': json.dumps({'public_id': {'$in': list(ASSESSMENTS.values())}}),
        })
        objects: dict[int, str] = dict(zip(ASSESSMENTS, (row['assigned_object'] for row in body['results'])))

        _assert_lines(objects, reader, with_type=False)


@pytest.mark.parametrize('reader', READERS)
class TestCiExplorer:
    """GET /ci_explorer/items"""

    def test_the_reference_value_shows_the_visible_owners(self, rest_api, reader: str) -> None:
        """The ticket node's flattened ref field is the asset's line"""
        lines: dict[int, str] = {}

        for asset, ticket in ((SHARED_ASSET, SHARED_TICKET), (EVE_ASSET, EVE_TICKET)):
            root: dict[str, Any] = _get(rest_api, f'{CI_EXPLORER_URL}?target_id={ticket}&with_root=true',
                                        reader)['root_node']
            lines[asset] = next(field['value'] for field in root['linked_object']['fields']
                                if field['name'] == ASSET_FIELD)

        _assert_lines(lines, reader)
