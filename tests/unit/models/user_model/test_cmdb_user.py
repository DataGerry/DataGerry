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
Unit tests for cmdb.models.user_model.cmdb_user

Pure: no Mongo, no Flask. CmdbUser is both the domain object and the storage document, so the two
serialisers are what most of this pins - `to_json` is what UsersManager persists and therefore HAS to
carry the password digest, while `to_public_json` is what every REST route and the login response
return and therefore must NOT. A round-trip test guards the pair against key-name drift, which is the
failure this model is most exposed to now that the keys are named once in `CmdbUserKey`.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.class_schema.user_model.cmdb_user_schema import (
    DEFAULT_API_LEVEL,
    DEFAULT_AUTHENTICATOR,
    DEFAULT_CONFIG_ITEMS_LIMIT,
    DEFAULT_DATABASE,
    DEFAULT_GROUP,
)
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.errors.models.cmdb_user import (
    CmdbUserInitError,
    CmdbUserInitFromDataError,
    CmdbUserToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
USER_NAME: str = 'alice'
DIGEST: str = 'KUPqsVxjxnmUmaJIdhan2d9MoBZIDV4Wtf9OsepxZUM='


def _user(**overrides: Any) -> CmdbUser:
    """Builds a CmdbUser with the mandatory arguments filled in."""
    kwargs: dict[str, Any] = {
        'public_id': PUBLIC_ID,
        'user_name': USER_NAME,
        'active': True,
    }
    kwargs.update(overrides)

    return CmdbUser(**kwargs)


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a stored CmdbUser document with the keys from_data requires."""
    document: dict[str, Any] = {
        CmdbUserKey.PUBLIC_ID.value: PUBLIC_ID,
        CmdbUserKey.USER_NAME.value: USER_NAME,
        CmdbUserKey.ACTIVE.value: True,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      __init__                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_defaults_come_from_the_schema_module() -> None:
    """An omitted optional argument falls back to the default the validation schema also declares"""
    user = _user()

    assert user.group_id == DEFAULT_GROUP
    assert user.authenticator == DEFAULT_AUTHENTICATOR
    assert user.database == DEFAULT_DATABASE
    assert user.api_level == DEFAULT_API_LEVEL
    assert user.config_items_limit == DEFAULT_CONFIG_ITEMS_LIMIT


def test_registration_time_defaults_to_now() -> None:
    """A user built without a registration time is stamped at construction"""
    before = datetime.now(timezone.utc)

    assert _user().registration_time >= before


@pytest.mark.parametrize('given, expected', [(None, DEFAULT_GROUP), (0, DEFAULT_GROUP), (5, 5)])
def test_a_falsy_group_id_falls_back_to_the_default(given: Any, expected: int) -> None:
    """Documented coercion: an omitted and a null group_id behave the same - so does an explicit 0"""
    assert _user(group_id=given).group_id == expected


@pytest.mark.parametrize('given', ['', None])
def test_an_empty_name_is_stored_as_none(given: Any) -> None:
    """Documented coercion: '' becomes None so get_display_name has one case fewer to handle"""
    user = _user(first_name=given, last_name=given)

    assert user.first_name is None
    assert user.last_name is None


def test_a_failing_init_is_wrapped() -> None:
    """Anything raised while building the user surfaces as CmdbUserInitError"""
    with pytest.raises(CmdbUserInitError):
        CmdbUser(public_id='not-an-id', user_name=USER_NAME, active=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       __str__                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_str_names_the_user_without_the_digest() -> None:
    """The readable form carries identity, never the password digest"""
    text = str(_user(password=DIGEST, email='alice@example.test'))

    assert USER_NAME in text
    assert 'alice@example.test' in text
    assert DIGEST not in text


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      from_data                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_reads_every_key() -> None:
    """A full document maps onto the matching attributes"""
    stamp = datetime(2026, 3, 1, tzinfo=timezone.utc)
    user = CmdbUser.from_data(_document(**{
        CmdbUserKey.GROUP_ID.value: 5,
        CmdbUserKey.REGISTRATION_TIME.value: stamp,
        CmdbUserKey.AUTHENTICATOR.value: 'LdapAuthenticationProvider',
        CmdbUserKey.DATABASE.value: 'tenant-a',
        CmdbUserKey.API_LEVEL.value: 2,
        CmdbUserKey.CONFIG_ITEMS_LIMIT.value: 25,
        CmdbUserKey.EMAIL.value: 'alice@example.test',
        CmdbUserKey.PASSWORD.value: DIGEST,
        CmdbUserKey.IMAGE.value: 'avatar.png',
        CmdbUserKey.FIRST_NAME.value: 'Ann',
        CmdbUserKey.LAST_NAME.value: 'Lee',
    }))

    assert (user.public_id, user.group_id, user.database, user.api_level) == (PUBLIC_ID, 5, 'tenant-a', 2)
    assert (user.config_items_limit, user.password, user.image) == (25, DIGEST, 'avatar.png')
    assert user.registration_time == stamp


def test_from_data_applies_the_defaults_for_absent_keys() -> None:
    """A minimal document is completed with the same defaults the constructor uses"""
    user = CmdbUser.from_data(_document())

    assert user.database == DEFAULT_DATABASE
    assert user.api_level == DEFAULT_API_LEVEL
    assert user.config_items_limit == DEFAULT_CONFIG_ITEMS_LIMIT
    assert user.password is None


def test_from_data_parses_a_string_registration_time() -> None:
    """A document whose timestamp came back as a string is parsed into a datetime"""
    user = CmdbUser.from_data(_document(**{CmdbUserKey.REGISTRATION_TIME.value: '2026-03-01T10:00:00'}))

    assert user.registration_time == datetime(2026, 3, 1, 10, 0, 0)


@pytest.mark.parametrize('missing', [CmdbUserKey.PUBLIC_ID, CmdbUserKey.USER_NAME, CmdbUserKey.ACTIVE])
def test_from_data_wraps_a_missing_required_key(missing: CmdbUserKey) -> None:
    """A document missing a mandatory key surfaces as CmdbUserInitFromDataError, not a KeyError"""
    document = _document()
    del document[missing.value]

    with pytest.raises(CmdbUserInitFromDataError):
        CmdbUser.from_data(document)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                to_json / to_public_json                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_to_json_is_the_storage_document_and_keeps_the_digest() -> None:
    """UsersManager persists exactly this dict, so dropping the digest here would wipe passwords"""
    document = CmdbUser.to_json(_user(password=DIGEST))

    assert set(document) == {key.value for key in CmdbUserKey}
    assert document[CmdbUserKey.PASSWORD.value] == DIGEST


def test_to_public_json_strips_the_digest() -> None:
    """Every REST route and the login response serialise through here - the digest must not leave"""
    document = CmdbUser.to_public_json(_user(password=DIGEST))

    assert CmdbUserKey.PASSWORD.value not in document
    assert set(document) == {key.value for key in CmdbUserKey} - {CmdbUserKey.PASSWORD.value}


def test_to_public_json_is_safe_for_a_user_without_a_password() -> None:
    """An externally provisioned user carries no digest; stripping an absent key is not an error"""
    assert CmdbUserKey.PASSWORD.value not in CmdbUser.to_public_json(_user())


def test_to_public_json_does_not_mutate_the_instance() -> None:
    """Serialising for a client must not cost the user its stored digest"""
    user = _user(password=DIGEST)

    CmdbUser.to_public_json(user)

    assert user.password == DIGEST
    assert CmdbUser.to_json(user)[CmdbUserKey.PASSWORD.value] == DIGEST


@pytest.mark.parametrize('serializer', [CmdbUser.to_json, CmdbUser.to_public_json])
def test_serialising_a_non_user_is_wrapped(serializer: Any) -> None:
    """The type guard reports a wrong argument as CmdbUserToJsonError, not an AttributeError"""
    with pytest.raises(CmdbUserToJsonError):
        serializer({'public_id': PUBLIC_ID})


def test_from_data_and_to_json_round_trip() -> None:
    """
    The two halves agree on every key name

    This is the regression that matters after moving both onto CmdbUserKey: a drift between what
    from_data reads and what to_json writes is a silently dropped field, not an error.
    """
    original = _user(
        password=DIGEST, email='alice@example.test', first_name='Ann', last_name='Lee',
        group_id=5, database='tenant-a', api_level=2, config_items_limit=25, image='avatar.png',
        registration_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    assert CmdbUser.to_json(CmdbUser.from_data(CmdbUser.to_json(original))) == CmdbUser.to_json(original)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  helper methods                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_database_returns_the_users_database() -> None:
    """The database name is what routes the user's requests in cloud mode"""
    assert _user(database='tenant-a').get_database() == 'tenant-a'


@pytest.mark.parametrize('first, last, expected', [
    ('Ann', 'Lee', 'Ann Lee'),
    ('Ann', None, USER_NAME),
    (None, 'Lee', USER_NAME),
    (None, None, USER_NAME),
    ('', '', USER_NAME),
])
def test_get_display_name(first: Any, last: Any, expected: str) -> None:
    """The full name needs BOTH parts; anything else falls back to the login name"""
    assert _user(first_name=first, last_name=last).get_display_name() == expected


@pytest.mark.parametrize('limit, count, expected', [
    (10, 9, False),
    (10, 10, True),
    (10, 11, True),
    (1, 0, False),
])
def test_is_config_item_limit_reached(limit: int, count: int, expected: bool) -> None:
    """The limit is inclusive: reaching it already blocks the next object"""
    assert _user(config_items_limit=limit).is_config_item_limit_reached(count) is expected


@pytest.mark.parametrize('limit', [None, 0])
def test_a_falsy_limit_is_replaced_by_the_default(limit: Any) -> None:
    """
    Current behaviour, pinned rather than endorsed (discussion-backlog #164)

    A falsy limit - an explicit 0 included - is treated as 'unset' and replaced with the default, and
    the replacement is written back onto the instance, so this predicate mutates the user it is asked
    about. A subscription capped at 0 config items therefore gets 1000.
    """
    user = _user(config_items_limit=limit)

    assert user.is_config_item_limit_reached(5) is False
    assert user.config_items_limit == DEFAULT_CONFIG_ITEMS_LIMIT
