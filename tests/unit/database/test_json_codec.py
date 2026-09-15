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
Unit tests for cmdb.database.json_codec

The BSON <-> JSON codec of the wire format. Pure tests: no Mongo, no Flask.

Two groups matter more than the per-type arms. First, the **round trip against real
`bson.json_util` output**, which is what the object and type managers actually feed `object_hook`:
its relaxed spelling of a datetime is an ISO string, its canonical one a nested `{'$numberLong': …}`,
and both used to be mishandled - the first by reading a naive timestamp as the host's LOCAL time
(every round-tripped date drifted by the server's UTC offset, invisibly on a UTC host), the second by
calling `float()` on a dict. Second, the **timezone** tests, which set TZ explicitly, because that
first bug cannot be seen from a UTC machine.

The malformed shapes are pinned too: `$options` is optional in MongoDB, a `$ref` without `$id` is not
a reference, and `{'$date': True}` is not one millisecond past the epoch - `bool` is an `int`
subclass, and `cmdb.utils.coerce_mongo_datetime`, the one decoder of that wrapper, refuses it.
"""
import datetime
import json
import re
import time
import uuid
from typing import Any

import pytest
from bson import json_util
from bson.objectid import ObjectId
from bson.dbref import DBRef
from bson.min_key import MinKey
from bson.max_key import MaxKey
from bson.timestamp import Timestamp

from cmdb.database.json_codec import MongoJsonKey, default, object_hook
# -------------------------------------------------------------------------------------------------------------------- #
#                                                    object_hook                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_object_hook_oid() -> None:
    """A {$oid} dict decodes to the matching ObjectId"""
    oid = ObjectId()
    assert object_hook({"$oid": str(oid)}) == oid


def test_object_hook_ref() -> None:
    """A {$ref,$id} dict decodes to a DBRef"""
    result = object_hook({"$ref": "objects", "$id": 42})
    assert isinstance(result, DBRef)
    assert result.collection == "objects"
    assert result.id == 42


def test_object_hook_date_from_millis() -> None:
    """A numeric {$date} (ms since epoch) decodes to a UTC datetime"""
    result = object_hook({"$date": 1609459200000})
    assert (result.year, result.month, result.day) == (2021, 1, 1)


def test_object_hook_date_from_isoformat() -> None:
    """A string {$date} decodes to the instant it names, UTC-aware

    Until 2026-09-09 this stripped the trailing 'Z' and called astimezone(utc) on the naive result,
    which read the timestamp as the HOST's local time - so the value was correct only on a UTC
    machine. The instant is pinned here for exactly that reason.
    """
    result = object_hook({"$date": "2021-01-01T00:00:00Z"})

    assert result == datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)


def test_object_hook_regex_with_flags() -> None:
    """A {$regex,$options} dict compiles a pattern with the i/m flags applied"""
    result = object_hook({"$regex": "abc", "$options": "im"})
    assert result.pattern == "abc"
    assert result.flags & re.IGNORECASE
    assert result.flags & re.MULTILINE


def test_object_hook_min_and_max_key() -> None:
    """{$minKey}/{$maxKey} decode to MinKey/MaxKey"""
    assert isinstance(object_hook({"$minKey": 1}), MinKey)
    assert isinstance(object_hook({"$maxKey": 1}), MaxKey)


def test_object_hook_uuid() -> None:
    """A {$uuid} dict decodes to a UUID"""
    value = uuid.uuid4()
    assert object_hook({"$uuid": value.hex}) == value


def test_object_hook_passthrough_for_plain_dict() -> None:
    """A dict without a special marker key is returned unchanged"""
    plain = {"name": "demo", "value": 1}
    assert object_hook(plain) is plain

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      default                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_default_objectid() -> None:
    """An ObjectId encodes to {$oid}"""
    oid = ObjectId()
    assert default(oid) == {"$oid": str(oid)}


def test_default_bytes_decoded() -> None:
    """bytes encode to their utf-8 string"""
    assert default(b"hello") == "hello"


def test_default_datetime_to_millis() -> None:
    """A datetime encodes to {$date: <ms since epoch>}"""
    assert default(datetime.datetime(2021, 1, 1, 0, 0, 0)) == {"$date": 1609459200000}


def test_default_regex() -> None:
    """A compiled pattern encodes to {$regex,$options}"""
    assert default(re.compile("abc", re.IGNORECASE | re.MULTILINE)) == {"$regex": "abc", "$options": "im"}


def test_default_min_and_max_key() -> None:
    """MinKey/MaxKey encode to their marker dicts"""
    assert default(MinKey()) == {"$minKey": 1}
    assert default(MaxKey()) == {"$maxKey": 1}


def test_default_timestamp() -> None:
    """A bson Timestamp encodes to {t,i}"""
    assert default(Timestamp(123, 4)) == {"t": 123, "i": 4}


def test_default_uuid() -> None:
    """A UUID encodes to {$uuid: hex}"""
    value = uuid.uuid4()
    assert default(value) == {"$uuid": value.hex}


def test_default_object_falls_back_to_dunder_dict() -> None:
    """An arbitrary object falls back to its __dict__"""
    class _Carrier:
        def __init__(self) -> None:
            self.x = 1
            self.y = "z"

    assert default(_Carrier()) == {"x": 1, "y": "z"}


def test_default_raises_type_error_when_not_serializable() -> None:
    """An object with neither a known type nor a __dict__ raises TypeError"""
    class _NoDict:
        __slots__ = ()

    with pytest.raises(TypeError):
        default(_NoDict())


@pytest.mark.parametrize('value', [ObjectId(), uuid.uuid4(), MinKey(), MaxKey()])
def test_codec_round_trip(value: Any) -> None:
    """default() output decodes back to the original value via object_hook()"""
    assert object_hook(default(value)) == value


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the round trip through bson.json_util                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheBsonRoundTrip:
    """
    What the object and type managers actually run: json_util encodes, object_hook decodes

    ``objects_manager.update_object`` and ``types_manager._as_stored_type_dict`` normalise a raw dict
    with ``json.loads(json.dumps(doc, default=json_util.default), object_hook=object_hook)``. So the
    input to `object_hook` is pymongo's extended JSON, whose datetime spelling depends on the value:
    an ISO string inside the relaxed range, a nested ``{'$numberLong': …}`` outside it.
    """

    @staticmethod
    def _round_trip(document: dict[str, Any]) -> dict[str, Any]:
        """Runs a document through the production round trip."""
        return json.loads(json.dumps(document, default=json_util.default), object_hook=object_hook)

    @pytest.mark.parametrize('timezone_name', ['UTC', 'Europe/Berlin', 'America/Los_Angeles'])
    def test_an_aware_datetime_survives_any_host_timezone(self, monkeypatch, timezone_name: str) -> None:
        """
        The bug this pins: a UTC timestamp used to come back shifted by the host's offset

        With TZ=Europe/Berlin, 10:00Z round-tripped to 08:00Z - so every write that normalised a
        document moved its dates, and no test on a UTC machine could see it.
        """
        monkeypatch.setenv('TZ', timezone_name)
        time.tzset()

        original = datetime.datetime(2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc)

        assert self._round_trip({'creation_time': original})['creation_time'] == original

    @pytest.mark.parametrize('timezone_name', ['UTC', 'Europe/Berlin'])
    def test_a_naive_datetime_is_read_as_utc(self, monkeypatch, timezone_name: str) -> None:
        """The driver is not tz_aware, so a naive value out of MongoDB is UTC - not local time"""
        monkeypatch.setenv('TZ', timezone_name)
        time.tzset()

        stored = datetime.datetime(2026, 9, 9, 10, 0, 0)

        assert self._round_trip({'creation_time': stored})['creation_time'] == datetime.datetime(
            2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc,
        )

    def test_a_pre_1970_date_survives(self) -> None:
        """
        Canonical extended JSON: `{'$date': {'$numberLong': '-315619200000'}}`

        pymongo spells any date outside the relaxed range this way, and `float()` on that dict raised
        an uncaught TypeError - so an object carrying such a date could not be written at all.
        """
        original = datetime.datetime(1960, 1, 1, tzinfo=datetime.timezone.utc)

        assert self._round_trip({'d': original})['d'] == original

    def test_a_far_future_date_survives(self) -> None:
        """The other end of the relaxed range takes the same spelling"""
        original = datetime.datetime(9999, 12, 31, tzinfo=datetime.timezone.utc)

        assert self._round_trip({'d': original})['d'] == original

    def test_an_objectid_survives(self) -> None:
        """
        The other BSON value a stored document carries into the round trip

        A native `uuid.UUID` does NOT: `json_util.default` refuses one under the driver's default
        UuidRepresentation, so only our own encoder (`default`) ever writes a `$uuid` wrapper.
        """
        document: dict[str, Any] = {'_id': ObjectId()}

        assert self._round_trip(document) == document

    def test_the_frontends_millis_wrapper_still_decodes(self) -> None:
        """
        The other producer of `{'$date': …}` is the Angular client, which sends epoch millis

        Its wrapper reaches `object_hook` unchanged (json.dumps passes a plain dict through), so both
        producers have to decode to the same instant.
        """
        document = {'creation_time': {'$date': 1788948000000}}

        assert self._round_trip(document)['creation_time'] == datetime.datetime(
            2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc,
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the shapes that used to raise                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMalformedDocumentsArePassedThrough:
    """A document the codec cannot decode stays a document - it never fails the write it is part of."""

    def test_a_regex_without_options_is_decoded(self) -> None:
        """`$options` is optional in MongoDB; reading it unguarded was a KeyError"""
        result = object_hook({MongoJsonKey.REGEX.value: 'abc'})

        assert result.pattern == 'abc'
        assert result.flags & re.IGNORECASE == 0

    def test_an_unknown_regex_option_is_ignored(self) -> None:
        """Only the flags the encoder can write back are read"""
        result = object_hook({MongoJsonKey.REGEX.value: 'abc', MongoJsonKey.OPTIONS.value: 'ixu'})

        assert result.flags & re.IGNORECASE
        assert result.flags & re.MULTILINE == 0

    def test_a_ref_without_an_id_is_not_a_reference(self) -> None:
        """It used to raise KeyError('$id') inside a JSON decode"""
        document = {MongoJsonKey.REF.value: 'framework.objects'}

        assert object_hook(document) is document

    @pytest.mark.parametrize('wrapped', [True, False], ids=['true', 'false'])
    def test_a_boolean_date_is_refused(self, wrapped: bool) -> None:
        """
        `bool` is an `int` subclass, so `{'$date': True}` used to decode to 1ms past the epoch

        `cmdb.utils.coerce_mongo_datetime` refuses it deliberately, and this codec delegates to it -
        the two implementations of one wire format may not disagree.
        """
        document = {MongoJsonKey.DATE.value: wrapped}

        assert object_hook(document) is document

    @pytest.mark.parametrize('wrapped', ['not-a-date', '', {'$numberLong': 'nope'}, []],
                             ids=['text', 'empty', 'bad-numberlong', 'list'])
    def test_an_unusable_date_is_passed_through(self, wrapped: Any) -> None:
        """A date-shaped key holding something else does not raise, and does not become a date"""
        document = {MongoJsonKey.DATE.value: wrapped}

        assert object_hook(document) is document

    def test_a_date_only_string_is_decoded(self) -> None:
        """'2026-09-09' used to be sliced to '2026-09-0' and raise ValueError"""
        result = object_hook({MongoJsonKey.DATE.value: '2026-09-09'})

        assert result == datetime.datetime(2026, 9, 9, tzinfo=datetime.timezone.utc)

    def test_an_offset_string_is_decoded_to_utc(self) -> None:
        """A non-Z offset survives too, because nothing slices the last character any more"""
        result = object_hook({MongoJsonKey.DATE.value: '2026-09-09T12:00:00+02:00'})

        assert result == datetime.datetime(2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          what default() falls back to                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheEncoderFallbacks:
    """An object that is no BSON type: its own to_json first, its __dict__ second."""

    def test_a_dbref_encodes_to_its_document(self) -> None:
        """The one BSON arm no test reached"""
        reference = DBRef('framework.objects', 42)

        assert default(reference) == reference.as_doc()

    def test_an_aware_datetime_is_shifted_to_utc_before_encoding(self) -> None:
        """The millis are the instant, whatever zone the value carried"""
        aware = datetime.datetime(2026, 9, 9, 12, 0, 0,
                                  tzinfo=datetime.timezone(datetime.timedelta(hours=2)))

        assert default(aware) == default(datetime.datetime(2026, 9, 9, 10, 0, 0))

    def test_sub_millisecond_precision_is_dropped(self) -> None:
        """MongoDB stores milliseconds, so the encoder truncates rather than rounds"""
        value = datetime.datetime(2026, 9, 9, 10, 0, 0, 999_999, tzinfo=datetime.timezone.utc)

        assert default(value)[MongoJsonKey.DATE.value] % 1000 == 999

    def test_an_instance_to_json_is_preferred(self) -> None:
        """The three classes a response hands over (RenderResult, SearchResult, SearchResultMap)"""
        class _Reporting:
            def __init__(self) -> None:
                self.private = 'not for the wire'

            def to_json(self) -> dict[str, Any]:
                """The public shape."""
                return {'public': True}

        assert default(_Reporting()) == {'public': True}

    def test_a_classmethod_to_json_is_not_called(self) -> None:
        """
        The models spell it `to_json(cls, instance)`

        Calling `obj.to_json()` on one raises a missing-argument TypeError, so only a plain instance
        method counts - a model reaching the encoder still falls back to its attributes.
        """
        class _Model:
            def __init__(self) -> None:
                self.public_id = 7

            @classmethod
            def to_json(cls, instance: Any) -> dict[str, Any]:
                """Never called by the encoder."""
                return {'called': 'wrongly', 'instance': instance}

        assert default(_Model()) == {'public_id': 7}

    def test_a_plain_dict_never_reaches_the_encoder(self) -> None:
        """
        json.dumps serialises dicts itself, so the removed `isinstance(obj, dict)` arm was dead

        Pinned as a fact about json.dumps rather than about this module: a dict subclass does not
        reach `default` either.
        """
        class _DictLike(dict):
            pass

        def _fail(value: Any) -> Any:
            raise AssertionError(f'default() was called for {value!r}')

        assert json.dumps({'a': _DictLike(x=1)}, default=_fail) == '{"a": {"x": 1}}'
