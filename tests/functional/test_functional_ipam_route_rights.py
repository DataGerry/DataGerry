"""
Functional tests for the ACL rights guarding the IPAM routes

Until 2026-09-16 not one of the nineteen IPAM routes carried a `.protect`. They gated on a valid token
plus the blueprint-level `LicenseFeature.IPAM` gate - which answers "is this installation entitled",
not "may this user" - so any authenticated account could read the whole address plan, export it, and
detach subnets and IPs.

`IpamRight.VIEW` now guards every read and `IpamRight.EDIT` the two unassign writes, mirroring the Rack
View feature, which is the same shape built later and was wired that way from the start.

**These tests exist because the rest of the IPAM suite cannot catch a regression here**: it drives the
routes with the full-access user, so removing a `.protect` would leave it entirely green. Each route is
therefore called with a user holding no rights at all, and must be refused.

**Every test unlocks the IPAM licence first, and that is not incidental.** The blueprint-level licence
gate answers **403** as well, so on an unlicensed installation - which is what the test suite is -
every one of these routes refuses everyone, and a test that merely asserted 403 would pass with no
`.protect` at all. Unlocking the feature leaves the rights check as the only thing that can refuse.
"""
from http import HTTPStatus

import pytest

from datetime import datetime, timezone

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

READ_ROUTES: list[tuple[str, str]] = [
    ('GET', '/ipam/tree/'),
    ('GET', '/ipam/tree/supernets/1'),
    ('GET', '/ipam/tree/unassigned'),
    ('GET', '/ipam/subnet/'),
    ('GET', '/ipam/subnet/overview/1'),
    ('GET', '/ipam/subnet/overview/1/sector'),
    ('GET', '/ipam/subnet/overview/1/invalid'),
    ('GET', '/ipam/subnet/overview/1/export'),
    ('GET', '/ipam/supernet/overview/1'),
    ('GET', '/ipam/supernet/overview/1/subnets/children/1'),
    ('GET', '/ipam/supernet/overview/1/subnets/export'),
    ('GET', '/ipam/supernet/overview/1/subnets/invalid'),
    ('GET', '/ipam/assignable-objects/'),
]

VALIDATION_ROUTES: list[tuple[str, str]] = [
    ('POST', '/ipam/validate/subnet'),
    ('POST', '/ipam/validate/supernet'),
    ('POST', '/ipam/validate/vlan'),
    ('POST', '/ipam/validate/interface'),
]

WRITE_ROUTES: list[tuple[str, str]] = [
    ('POST', '/ipam/subnet/overview/1/unassign'),
    ('POST', '/ipam/supernet/overview/1/subnets/unassign'),
]

ALL_ROUTES: list[tuple[str, str]] = READ_ROUTES + VALIDATION_ROUTES + WRITE_ROUTES


RIGHTLESS_ID: int = 990101


@pytest.fixture(name='rightless_user')
def fixture_rightless_user(database_manager, database_name):
    """
    A user that really exists in the database and holds no rights

    The session's `none_access_user` fixture is not enough here: it is never inserted, so
    `insert_request_user` cannot resolve it and the request is refused **401** before any right is
    consulted - which would prove nothing about the guard. This one is written to the database so the
    only thing left to refuse it is the right.
    """
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    groups.delete_one({'public_id': RIGHTLESS_ID})
    users.delete_one({'public_id': RIGHTLESS_ID})

    groups.insert_one({
        'public_id': RIGHTLESS_ID,
        'name': 'rightless',
        'label': 'Rightless',
        'rights': [],
    })
    users.insert_one({
        'public_id': RIGHTLESS_ID,
        'user_name': 'rightless-user',
        'active': True,
        'group_id': RIGHTLESS_ID,
        'registration_time': datetime.now(timezone.utc),
        'email': 'rightless@example.com',
        'password': 'x',
        'authenticator': 'LocalAuthenticationProvider',
    })

    yield CmdbUser(
        public_id=RIGHTLESS_ID,
        user_name='rightless-user',
        active=True,
        group_id=RIGHTLESS_ID,
        registration_time=datetime.now(timezone.utc),
    )

    groups.delete_one({'public_id': RIGHTLESS_ID})
    users.delete_one({'public_id': RIGHTLESS_ID})


@pytest.fixture(name='ipam_licensed', autouse=True)
def fixture_ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Unlocks the IPAM feature so the licence gate cannot be what refuses

    Both guards answer 403. Without this the suite's unlicensed installation refuses every route to
    everyone and these tests would pass against code carrying no rights at all.
    """
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )


def _call(rest_api, method: str, route: str, user=None):
    """Issues one request, optionally as a specific user."""
    kwargs = {'user': user} if user is not None else {}

    if method == 'POST':
        return rest_api.post(route, json={}, **kwargs)

    return rest_api.get(route, **kwargs)


@pytest.mark.parametrize('method, route', ALL_ROUTES)
def test_a_user_without_rights_is_refused(rest_api, rightless_user, method: str, route: str) -> None:
    """Every IPAM route, called by an account that exists and holds no rights at all."""
    response = _call(rest_api, method, route, user=rightless_user)

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('method, route', ALL_ROUTES)
def test_the_full_access_user_is_not_refused(rest_api, method: str, route: str) -> None:
    """
    The guard must refuse the right thing and nothing else

    A right that refuses everyone is indistinguishable from a broken route, so the negative test above
    only means something next to this one. These may answer 400/404/500 on the empty fixture database -
    what matters is that the refusal is not an authorisation one.

    This is also the test that would have caught the licence gate masking everything: before the
    `ipam_licensed` fixture was added, all fifteen of these failed with 403.
    """
    response = _call(rest_api, method, route)

    assert response.status_code != HTTPStatus.FORBIDDEN


class TestTheMapping:
    """Which right guards which route."""

    def test_every_ipam_route_is_protected(self) -> None:
        """
        Counted at the source, so a route added without a right fails here

        The gap this closes was measured the same way: `grep -c '.protect(' ipam_routes/` returned 0
        across all five files.
        """
        from pathlib import Path

        folder = Path('cmdb/interface/rest_api/routes/ipam_routes')
        routes = sum(path.read_text(encoding='utf-8').count('blueprint.route(') for path in folder.glob('ipam_*routes.py'))
        guards = sum(path.read_text(encoding='utf-8').count('.protect(') for path in folder.glob('ipam_*routes.py'))

        assert routes == guards == len(ALL_ROUTES)

    def test_only_the_two_unassign_writes_require_edit(self) -> None:
        """
        Everything else reads, including the exports and the four validators

        The validators read the database - they check a candidate CIDR against existing siblings - so
        VIEW is the honest mapping for them; they write nothing.
        """
        from pathlib import Path

        folder = Path('cmdb/interface/rest_api/routes/ipam_routes')
        edits = sum(path.read_text(encoding='utf-8').count('IpamRight.EDIT') for path in folder.glob('ipam_*routes.py'))

        assert edits == len(WRITE_ROUTES)
