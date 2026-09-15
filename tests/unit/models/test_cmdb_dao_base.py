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
Unit tests for the non-shared half of cmdb.models.cmdb_dao.CmdbDAO

Pure tests: no Mongo, no Flask. ``test_cmdb_dao_shared_document.py`` covers the shared ``from_data`` /
``to_json`` added during the ISMS lift; this module covers the half that predates it and that nothing
had ever tested - the keyword-to-attribute loop, the required-key refusal, the public_id accessor, the
index materialisation, and the versioning trio every object edit runs through.

The versioning half is where the defects were:

  - ``update_version`` **returned** the new version without storing it, so a caller that wrote the
    return value into the document left the instance one bump behind - and the edit log, which reads
    ``get_version()`` off that instance, recorded the stale one
  - an unrecognised bump constant fell through to a patch bump instead of being refused
  - a stored version that is not 'major.minor.patch' escaped as a raw ValueError from int()

A local model stands in for a real one, so the base class is tested on its own terms
"""
from typing import Any

import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.errors.cmdb_object import (
    CmdbDAOError,
    NoPublicIDError,
    NoVersionError,
    RequiredInitKeyNotFoundError,
    VersionTypeError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 12


class _Thing(CmdbDAO):
    """A minimal CmdbDAO subclass: no KEYS, so it keeps the keyword-to-attribute behaviour"""
    COLLECTION = 'test.things'
    REQUIRED_INIT_KEYS: list[str] = ['label']
    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('label', CmdbDAO.DAO_ASCENDING)], 'name': 'label', 'unique': False},
    ]


def _thing(**kwargs: Any) -> _Thing:
    """Builds the local model with the required keys plus whatever the test adds"""
    arguments: dict[str, Any] = {'public_id': PUBLIC_ID, 'label': 'a label'}
    arguments.update(kwargs)

    return _Thing(**arguments)


class TestConstruction:
    """What __new__ refuses and what __init__ keeps."""

    def test_a_missing_required_key_is_refused_before_init_runs(self) -> None:
        """
        The check is on __new__, so the instance is never created rather than half-built

        REQUIRED_INIT_KEYS is checked against the KEYWORD arguments, which is why every model in the
        repo is constructed by keyword.
        """
        with pytest.raises(RequiredInitKeyNotFoundError) as caught:
            _Thing(public_id=PUBLIC_ID)

        assert 'label' in str(caught.value)

    def test_public_id_itself_is_a_required_key(self) -> None:
        """It comes from SUPER_INIT_KEYS, so every model inherits the demand."""
        with pytest.raises(RequiredInitKeyNotFoundError) as caught:
            _Thing(label='a label')

        assert CmdbDAO.PUBLIC_ID_KEY in str(caught.value)

    def test_a_positional_call_cannot_satisfy_the_check(self) -> None:
        """__new__ reads kwargs only, which is what makes positional construction impossible."""
        with pytest.raises(RequiredInitKeyNotFoundError):
            _Thing(PUBLIC_ID)

    def test_the_public_id_is_coerced_to_an_integer(self) -> None:
        """A document storing it as a string still reads."""
        assert _thing(public_id='7').public_id == 7

    def test_every_other_keyword_becomes_an_attribute(self) -> None:
        """
        The loop six models still rely on, CmdbSectionTemplate and CmdbReport among them

        Its 'version' branch used to do character for character what setattr does, and is gone.
        """
        thing = _thing(anything='kept', version='2.0.0')

        assert thing.anything == 'kept'
        assert thing.version == '2.0.0'


class TestPublicId:
    """The accessor the shared to_json reads through."""

    def test_returns_the_assigned_id(self) -> None:
        """The ordinary case."""
        assert _thing().get_public_id() == PUBLIC_ID

    def test_an_unassigned_id_is_refused(self) -> None:
        """
        Zero is the "not yet inserted" marker, and a response carrying it would be unusable

        The shared to_json reads public_id through here for exactly this reason.
        """
        with pytest.raises(NoPublicIDError):
            _thing(public_id=0).get_public_id()


class TestIndexMaterialisation:
    """What CollectionValidator receives."""

    def test_the_declared_and_inherited_indexes_are_materialised_together(self) -> None:
        """A model's own indexes plus the unique public_id one every collection gets."""
        names = {index.document['name'] for index in _Thing.get_index_keys()}

        assert names == {'label', CmdbDAO.PUBLIC_ID_KEY}

    def test_the_inherited_public_id_index_is_unique(self) -> None:
        """The identity guarantee of every collection in the product."""
        public_id_index = next(
            index for index in _Thing.get_index_keys()
            if index.document['name'] == CmdbDAO.PUBLIC_ID_KEY
        )

        assert public_id_index.document['unique'] is True

    def test_redeclaring_an_inherited_index_name_is_refused(self) -> None:
        """
        Index reconciliation matches on the NAME and is additive, so the second declaration would be
        silently ignored - the collection would keep whichever definition reached it first, and the
        model would look like it had asked for something it never got
        """
        class _Clashing(CmdbDAO):
            """A model redeclaring the inherited index name"""
            COLLECTION = 'test.clashing'
            INDEX_KEYS: list[dict[str, Any]] = [
                {'keys': [(CmdbDAO.PUBLIC_ID_KEY, CmdbDAO.DAO_ASCENDING)],
                 'name': CmdbDAO.PUBLIC_ID_KEY, 'unique': False},
            ]

        with pytest.raises(CmdbDAOError) as caught:
            _Clashing.get_index_keys()

        assert CmdbDAO.PUBLIC_ID_KEY in str(caught.value)

    def test_a_model_declaring_nothing_still_gets_the_identity_index(self) -> None:
        """The default INDEX_KEYS is empty, and the inherited one is not optional."""
        class _Bare(CmdbDAO):
            """A model with no indexes of its own"""
            COLLECTION = 'test.bare'

        assert [index.document['name'] for index in _Bare.get_index_keys()] == [CmdbDAO.PUBLIC_ID_KEY]


class TestUpdateVersion:
    """The bump every object edit runs through."""

    def test_the_new_version_is_stored_on_the_instance_and_returned(self) -> None:
        """
        It used to only return the string

        The object update writes the return value into the document while the edit log reads
        get_version() off the instance, so the log recorded every edit one bump behind the object it
        described.
        """
        thing = _thing(version='1.2.3')

        returned: str = thing.update_version(CmdbDAO.VERSIONING_PATCH)

        assert returned == '1.2.4'
        assert thing.version == '1.2.4'
        assert thing.get_version() == returned

    @pytest.mark.parametrize('bump, expected', [
        (CmdbDAO.VERSIONING_MAJOR, '2.0.0'),
        (CmdbDAO.VERSIONING_MINOR, '1.3.0'),
        (CmdbDAO.VERSIONING_PATCH, '1.2.4'),
    ], ids=['major', 'minor', 'patch'])
    def test_each_constant_selects_its_own_bump(self, bump: int, expected: str) -> None:
        """The three selectors, and the semver resets they now apply."""
        thing = _thing(version='1.2.3')

        assert thing.update_version(bump) == expected

    def test_an_unknown_bump_constant_is_refused(self) -> None:
        """
        It used to fall through to a patch bump

        So a typo'd or future constant degraded silently - the version still moved, just not the way
        the caller asked.
        """
        thing = _thing(version='1.2.3')

        with pytest.raises(VersionTypeError) as caught:
            thing.update_version(99)

        assert '99' in str(caught.value)
        assert thing.version == '1.2.3'

    def test_an_instance_without_a_version_is_refused(self) -> None:
        """There is nothing to bump, and inventing 1.0.1 would invent a history."""
        with pytest.raises(NoVersionError):
            _thing().update_version(CmdbDAO.VERSIONING_PATCH)

    @pytest.mark.parametrize('stored', [None, ''], ids=['none', 'empty'])
    def test_the_emptiness_rule_matches_get_version(self, stored: Any) -> None:
        """
        '' used to pass this guard and die inside int('')

        The two accessors now agree on what "no version" means.
        """
        thing = _thing(version=stored)

        with pytest.raises(NoVersionError):
            thing.update_version(CmdbDAO.VERSIONING_PATCH)

    @pytest.mark.parametrize('stored', ['v1', '1.2.x', '1.2.3.4'], ids=['prefixed', 'letter', 'four_parts'])
    def test_an_unreadable_version_surfaces_as_a_domain_error(self, stored: str) -> None:
        """
        A raw ValueError from int() used to escape the model, past the caller's error mapping

        The message names the object and the value, which is what an operator needs to fix the
        document.
        """
        thing = _thing(version=stored)

        with pytest.raises(VersionTypeError) as caught:
            thing.update_version(CmdbDAO.VERSIONING_PATCH)

        assert stored in str(caught.value)

    def test_a_two_part_version_is_completed_rather_than_refused(self) -> None:
        """
        '1.2' bumps to '1.2.1': the missing patch component defaults to 0 before the bump

        Pinned as the tolerated case, so that tightening it later is a decision rather than a
        surprise.
        """
        thing = _thing(version='1.2')

        assert thing.update_version(CmdbDAO.VERSIONING_PATCH) == '1.2.1'


class TestGetVersion:
    """The read half."""

    def test_returns_the_stored_version(self) -> None:
        """The ordinary case."""
        assert _thing(version='3.1.4').get_version() == '3.1.4'

    @pytest.mark.parametrize('stored', [None, ''], ids=['none', 'empty'])
    def test_no_version_is_refused(self, stored: Any) -> None:
        """Same emptiness rule as update_version."""
        with pytest.raises(NoVersionError):
            _thing(version=stored).get_version()

    def test_an_instance_that_never_had_a_version_is_refused(self) -> None:
        """A model that carries no version attribute at all reaches the same answer."""
        with pytest.raises((NoVersionError, AttributeError)):
            _thing().get_version()


class TestRepr:
    """What a model prints as, which is what reaches a log line or a debugger."""

    def test_names_the_class_and_its_attributes(self) -> None:
        """
        Used by the object-update render_state and by every LOGGER call that formats a model

        Pinned lightly: the exact layout is pprint's, but the class name and the stored values have
        to be in it for a log line to be worth anything.
        """
        printed: str = repr(_thing(version='1.2.3'))

        assert '_Thing' in printed
        assert 'a label' in printed
        assert '1.2.3' in printed
