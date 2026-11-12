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
Unit tests for cmdb.utils.omitted_keys - an update completed from the stored document
"""
from typing import Any

import pytest

from cmdb.utils import keep_omitted_keys
# -------------------------------------------------------------------------------------------------------------------- #

STORED: dict[str, Any] = {'name': 'stored', 'active': False, 'limit': 50, 'secret': 'digest'}
IMPORT_EMPTY_VALUES: tuple[Any, ...] = (None, '')


def test_every_omitted_key_takes_the_stored_value() -> None:
    """An empty payload is the stored document"""
    assert keep_omitted_keys({}, STORED) == STORED


@pytest.mark.parametrize('sent', [False, 0, None, '', [], 'new'],
                         ids=['false', 'zero', 'none', 'empty-string', 'empty-list', 'value'])
def test_a_sent_key_wins_whatever_its_value(sent: Any) -> None:
    """Without empty_values only an absent key is an omission - False, 0 and None are values"""
    assert keep_omitted_keys({'active': sent}, STORED)['active'] == sent


def test_an_excluded_key_is_never_taken() -> None:
    """A secret the read never answers stays out"""
    assert 'secret' not in keep_omitted_keys({}, STORED, excluded={'secret'})


def test_an_excluded_key_the_payload_sends_is_kept_as_sent() -> None:
    """Excluding is about filling, not about removing"""
    assert keep_omitted_keys({'secret': 'sent'}, STORED, excluded={'secret'})['secret'] == 'sent'


def test_only_the_named_keys_are_completed() -> None:
    """``keys`` narrows the completion"""
    assert keep_omitted_keys({'name': 'sent'}, STORED, keys=['active']) == {'name': 'sent', 'active': False}


def test_a_named_key_the_stored_document_lacks_stays_out() -> None:
    """Nothing to take - the payload is not padded with None"""
    assert keep_omitted_keys({}, STORED, keys=['missing']) == {}


@pytest.mark.parametrize('empty', IMPORT_EMPTY_VALUES, ids=['none', 'empty-string'])
def test_an_empty_value_counts_as_omitted_when_named(empty: Any) -> None:
    """The importer's spelling of "empty" takes the stored value"""
    assert keep_omitted_keys({'active': empty}, STORED, empty_values=IMPORT_EMPTY_VALUES)['active'] is False


@pytest.mark.parametrize('sent', [False, 0], ids=['false', 'zero'])
def test_a_falsy_value_is_no_empty_value(sent: Any) -> None:
    """``False`` and ``0`` are values even with the importer's empty values named"""
    assert keep_omitted_keys({'active': sent}, STORED, empty_values=IMPORT_EMPTY_VALUES)['active'] is sent


def test_a_payload_key_the_stored_document_lacks_stays() -> None:
    """A new key the body sends is the body's"""
    assert keep_omitted_keys({'extra': 1}, STORED)['extra'] == 1


def test_neither_argument_is_mutated() -> None:
    """A new dict"""
    payload: dict[str, Any] = {'name': 'sent'}
    stored: dict[str, Any] = dict(STORED)

    keep_omitted_keys(payload, stored)

    assert payload == {'name': 'sent'}
    assert stored == STORED
