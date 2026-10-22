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
Unit tests for the best-practice model catalogue (``best_practice_catalogue`` + ``best_practice_meta_schema``)

Model folders are written into ``tmp_path``, so every rule of the file contract is driven from real files: which
files a folder offers, how a pair is judged (the id, the description file, the model file) and in which order, that a
pair which cannot be offered is left out and logged without stopping the others, the card order, and the bundled
folder - every pair in it loads, so a broken bundle fails here before it ships
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cmdb.errors.configuration_transfer import BestPracticeModelError
from cmdb.framework.configuration_transfer import best_practice_catalogue as catalogue_module
from cmdb.framework.configuration_transfer.best_practice_catalogue import (
    BestPracticeCatalogue,
    BestPracticeMeta,
    BestPracticeModel,
    build_meta,
    default_models_folder,
    find_model_files,
    find_orphan_meta_files,
    get_best_practice_catalogue,
    load_catalogue,
    load_model,
    meta_path_of,
    model_id_of,
    read_json_file,
)
from cmdb.framework.configuration_transfer.best_practice_constants import (
    BEST_PRACTICE_MODELS_FOLDER,
    META_FILE_SUFFIX,
    MODEL_FILE_SUFFIX,
    META_FILE_INVALID,
    META_FILE_MISSING,
    MODEL_FILE_PROBLEMS,
    BestPracticeMetaKey,
)
from cmdb.framework.configuration_transfer.best_practice_meta_schema import ORDER_NOT_A_NUMBER, reject_boolean
from cmdb.framework.configuration_transfer.transfer_components import TRANSFER_COMPONENT_NAMES
from cmdb.framework.configuration_transfer.transfer_file import build_component_section, build_transfer_file
# -------------------------------------------------------------------------------------------------------------------- #

DB_VERSION: int = 20261021
EXPORTED_AT: datetime = datetime(2026, 10, 22, 9, 30, tzinfo=timezone.utc)
FIRST_ID: str = 'it_infrastructure'
SECOND_ID: str = 'workplace'
THIRD_ID: str = 'network'
FIRST_ORDER: int = 20
SECOND_ORDER: int = 10
README_NAME: str = 'README.md'
CATALOGUE_LOGGER: str = catalogue_module.LOGGER.name
DATE_KEY: str = 'registered'
DATE_MILLIS: int = 1761125400000
BROKEN_FILE_NAME: str = 'broken.json'
ABSENT_NAME: str = 'absent'
BROKEN_JSON: str = '{broken'

TITLE: str = BestPracticeMetaKey.TITLE.value
BADGE: str = BestPracticeMetaKey.BADGE.value
SUMMARY: str = BestPracticeMetaKey.SUMMARY.value
DESCRIPTION: str = BestPracticeMetaKey.DESCRIPTION.value
SUITED_FOR: str = BestPracticeMetaKey.SUITED_FOR.value
PROFILES: str = BestPracticeMetaKey.PROFILES.value
CATEGORY_DESCRIPTIONS: str = BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value
ORDER: str = BestPracticeMetaKey.ORDER.value

META: dict[str, Any] = {
    TITLE: 'IT Infrastructure',
    BADGE: 'Complete CMDB',
    SUMMARY: 'Every asset class in one connected model.',
    DESCRIPTION: 'A full CMDB.\nWorkplace devices, servers and network components.',
    SUITED_FOR: ['IT departments of mid-sized companies', 'Service providers'],
    PROFILES: ['user-management', 'location'],
    CATEGORY_DESCRIPTIONS: {'contact': 'People and organizations'},
    ORDER: FIRST_ORDER,
}


def _transfer_file() -> dict[str, Any]:
    """A transfer file whose envelope is usable - every component, no documents"""
    return build_transfer_file(
        DB_VERSION, {name: build_component_section(0, []) for name in TRANSFER_COMPONENT_NAMES}, EXPORTED_AT,
    )


def _write(path: Path, content: Any) -> Path:
    """Writes `content` as JSON - or as given, when it is a str or bytes"""
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding='utf-8')
    else:
        path.write_text(json.dumps(content), encoding='utf-8')

    return path


def _pair(folder: Path, model_id: str, meta: Any = None, model: Any = None) -> Path:
    """Writes one model pair; returns the model file"""
    _write(folder / f'{model_id}{META_FILE_SUFFIX}', META if meta is None else meta)

    return _write(folder / f'{model_id}{MODEL_FILE_SUFFIX}', _transfer_file() if model is None else model)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the folder                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheFolder:
    """Which files a folder offers"""

    def test_model_files_are_the_json_files_that_are_not_descriptions(self, tmp_path: Path) -> None:
        """Description files, other files and folders are no model files; sorted by name"""
        _pair(tmp_path, SECOND_ID)
        _pair(tmp_path, FIRST_ID)
        _write(tmp_path / README_NAME, '# models')
        (tmp_path / f'nested{MODEL_FILE_SUFFIX}').mkdir()

        assert [path.name for path in find_model_files(tmp_path)] == [
            f'{FIRST_ID}{MODEL_FILE_SUFFIX}', f'{SECOND_ID}{MODEL_FILE_SUFFIX}',
        ]

    def test_a_missing_folder_offers_nothing(self, tmp_path: Path) -> None:
        """No folder, no models - and no orphans"""
        assert not find_model_files(tmp_path / ABSENT_NAME)
        assert not find_orphan_meta_files(tmp_path / ABSENT_NAME)

    def test_a_description_without_its_model_is_an_orphan(self, tmp_path: Path) -> None:
        """Only the one whose model file is missing"""
        _pair(tmp_path, FIRST_ID)
        _write(tmp_path / f'{SECOND_ID}{META_FILE_SUFFIX}', META)

        assert [path.name for path in find_orphan_meta_files(tmp_path)] == [f'{SECOND_ID}{META_FILE_SUFFIX}']

    def test_the_id_and_the_description_file_follow_from_the_model_file(self, tmp_path: Path) -> None:
        """`<id>.json` -> `<id>` and `<id>.meta.json`"""
        model_path: Path = tmp_path / f'{FIRST_ID}{MODEL_FILE_SUFFIX}'

        assert model_id_of(model_path) == FIRST_ID
        assert meta_path_of(model_path) == tmp_path / f'{FIRST_ID}{META_FILE_SUFFIX}'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    reading a file                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadJsonFile:
    """A file of a pair is UTF-8 JSON, decoded as an uploaded transfer file is"""

    def test_a_date_reads_as_a_datetime(self, tmp_path: Path) -> None:
        """The export writes `{'$date': millis}`; the import expects the datetime back"""
        path = _write(tmp_path / 'dated.json', {DATE_KEY: {'$date': DATE_MILLIS}})

        decoded = read_json_file(path)[DATE_KEY]

        assert isinstance(decoded, datetime)
        assert decoded.timestamp() * 1000 == DATE_MILLIS

    @pytest.mark.parametrize('content', [b'\xff\xfe{}', '{"unterminated": ', ''], ids=['no-utf8', 'no-json', 'empty'])
    def test_an_unreadable_file_names_itself(self, tmp_path: Path, content: Any) -> None:
        """The error says which file"""
        path = _write(tmp_path / BROKEN_FILE_NAME, content)

        with pytest.raises(BestPracticeModelError) as exc_info:
            read_json_file(path)

        assert BROKEN_FILE_NAME in str(exc_info.value)

    def test_a_missing_file_is_the_same_error(self, tmp_path: Path) -> None:
        """Not an OSError escaping the catalogue"""
        with pytest.raises(BestPracticeModelError):
            read_json_file(tmp_path / f'{ABSENT_NAME}{MODEL_FILE_SUFFIX}')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the description file                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildMeta:
    """The description file fits its schema, or names what does not"""

    def test_a_valid_file_builds_the_description(self) -> None:
        """Every key read into its field - distinct values, so a swapped key shows"""
        assert build_meta(META) == BestPracticeMeta(
            title=META[TITLE], badge=META[BADGE], summary=META[SUMMARY], description=META[DESCRIPTION],
            suited_for=tuple(META[SUITED_FOR]), profiles=tuple(META[PROFILES]),
            category_descriptions=META[CATEGORY_DESCRIPTIONS], order=FIRST_ORDER,
        )

    def test_empty_lists_and_no_category_descriptions_are_valid(self) -> None:
        """A model may name no audience, no profiles, describe no category"""
        meta = build_meta({**META, SUITED_FOR: [], PROFILES: [], CATEGORY_DESCRIPTIONS: {}})

        assert (meta.suited_for, meta.profiles, meta.category_descriptions) == ((), (), {})

    @pytest.mark.parametrize('key', [key.value for key in BestPracticeMetaKey])
    def test_every_key_is_required(self, key: str) -> None:
        """A missing key is named"""
        with pytest.raises(BestPracticeModelError) as exc_info:
            build_meta({name: value for name, value in META.items() if name != key})

        assert key in str(exc_info.value)

    @pytest.mark.parametrize('change', [
        {'tagline': 'misspelt key'},
        {TITLE: '   '},
        {DESCRIPTION: ' \n\t '},
        {TITLE: 7},
        {SUITED_FOR: 'not a list'},
        {PROFILES: ['ok', '']},
        {CATEGORY_DESCRIPTIONS: {'contact': ' '}},
        {CATEGORY_DESCRIPTIONS: ['contact']},
        {ORDER: -1},
        {ORDER: 1.5},
        {ORDER: True},
    ], ids=['unknown-key', 'blank-title', 'blank-multiline', 'title-no-text', 'list-no-list', 'blank-list-entry',
            'blank-description-value', 'descriptions-no-object', 'negative-order', 'fraction-order', 'boolean-order'])
    def test_an_invalid_value_is_refused(self, change: dict[str, Any]) -> None:
        """The file is written by hand: nothing unusable passes"""
        with pytest.raises(BestPracticeModelError):
            build_meta({**META, **change})

    @pytest.mark.parametrize('data', [[META], 'meta', None], ids=['list', 'text', 'null'])
    def test_a_file_that_is_no_object_is_refused(self, data: Any) -> None:
        """Named by its type"""
        with pytest.raises(BestPracticeModelError) as exc_info:
            build_meta(data)

        assert type(data).__name__ in str(exc_info.value)

    def test_the_boolean_check_reports_only_a_boolean(self) -> None:
        """A whole number passes it"""
        errors: list[tuple[str, str]] = []

        reject_boolean(ORDER, FIRST_ORDER, lambda field, message: errors.append((field, message)))
        reject_boolean(ORDER, False, lambda field, message: errors.append((field, message)))

        assert errors == [(ORDER, ORDER_NOT_A_NUMBER)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     one pair                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLoadModel:
    """One pair: the id, the description file, the model file"""

    def test_a_valid_pair_loads(self, tmp_path: Path) -> None:
        """The id from the file name, the description built, the document decoded"""
        model = load_model(_pair(tmp_path, FIRST_ID))

        assert model.model_id == FIRST_ID
        assert model.meta == build_meta(META)
        assert model.document == _transfer_file()

    @pytest.mark.parametrize('model_id', ['IT_Infrastructure', 'it-infrastructure', 'it infrastructure', 'é'],
                             ids=['upper-case', 'hyphen', 'space', 'non-ascii'])
    def test_a_misspelt_id_is_refused(self, tmp_path: Path, model_id: str) -> None:
        """Only lower-case letters, digits and '_'"""
        with pytest.raises(BestPracticeModelError) as exc_info:
            load_model(_pair(tmp_path, model_id))

        assert model_id in str(exc_info.value)

    def test_a_missing_description_file_is_refused(self, tmp_path: Path) -> None:
        """Named"""
        model_path = _write(tmp_path / f'{FIRST_ID}{MODEL_FILE_SUFFIX}', _transfer_file())

        with pytest.raises(BestPracticeModelError) as exc_info:
            load_model(model_path)

        assert str(exc_info.value) == META_FILE_MISSING.format(file_name=f'{FIRST_ID}{META_FILE_SUFFIX}')

    @pytest.mark.parametrize('model', [[], {'format_version': 1}], ids=['no-object', 'no-envelope'])
    def test_a_model_file_that_is_no_transfer_file_is_refused(self, tmp_path: Path, model: Any) -> None:
        """The envelope's problems are named"""
        with pytest.raises(BestPracticeModelError) as exc_info:
            load_model(_pair(tmp_path, FIRST_ID, model=model))

        assert str(exc_info.value).startswith(MODEL_FILE_PROBLEMS.split('{', maxsplit=1)[0])

    def test_an_invalid_description_is_refused_before_the_model_is_read(self, tmp_path: Path) -> None:
        """The description file is judged first: a broken model file is not even read"""
        model_path = _pair(tmp_path, FIRST_ID, meta={**META, ORDER: -1}, model=BROKEN_JSON)

        with pytest.raises(BestPracticeModelError) as exc_info:
            load_model(model_path)

        assert str(exc_info.value).startswith(META_FILE_INVALID.split('{', maxsplit=1)[0])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the catalogue                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLoadCatalogue:
    """Every pair that can be offered, in card order; the others left out and logged"""

    def test_the_models_are_in_card_order(self, tmp_path: Path) -> None:
        """By `order`, then by id"""
        _pair(tmp_path, FIRST_ID, meta={**META, ORDER: FIRST_ORDER})
        _pair(tmp_path, SECOND_ID, meta={**META, ORDER: SECOND_ORDER})
        _pair(tmp_path, THIRD_ID, meta={**META, ORDER: FIRST_ORDER})

        assert [model.model_id for model in load_catalogue(tmp_path).models] == [SECOND_ID, FIRST_ID, THIRD_ID]

    def test_a_broken_pair_is_left_out_and_logged_without_stopping_the_others(
            self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """One ERROR per left-out pair - the orphaned description included - naming the model"""
        _pair(tmp_path, FIRST_ID)
        _pair(tmp_path, SECOND_ID, model=BROKEN_JSON)
        _write(tmp_path / f'{THIRD_ID}{META_FILE_SUFFIX}', META)
        caplog.set_level(logging.ERROR, logger=CATALOGUE_LOGGER)

        catalogue = load_catalogue(tmp_path)

        assert [model.model_id for model in catalogue.models] == [FIRST_ID]
        left_out = [record.getMessage() for record in caplog.records if record.name == CATALOGUE_LOGGER]
        assert len(left_out) == 2
        assert SECOND_ID in left_out[0] and THIRD_ID in left_out[1]

    def test_a_model_is_found_by_its_id(self, tmp_path: Path) -> None:
        """And an unknown id is None"""
        _pair(tmp_path, FIRST_ID)
        catalogue = load_catalogue(tmp_path)

        assert catalogue.get(FIRST_ID).model_id == FIRST_ID
        assert catalogue.get(SECOND_ID) is None

    def test_an_empty_folder_is_an_empty_catalogue(self, tmp_path: Path) -> None:
        """Nothing to offer is no error"""
        assert not load_catalogue(tmp_path).models

    def test_the_catalogue_keeps_its_order_whatever_it_was_handed(self) -> None:
        """The constructor sorts"""
        first = BestPracticeModel(FIRST_ID, build_meta(META), {})
        second = BestPracticeModel(SECOND_ID, build_meta({**META, ORDER: SECOND_ORDER}), {})

        assert BestPracticeCatalogue([first, second]).models == (second, first)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the bundled folder                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheBundledFolder:
    """The folder that ships: every pair in it loads"""

    def test_the_folder_sits_next_to_the_catalogue_module(self) -> None:
        """Where the binary bundles it too"""
        folder = default_models_folder()

        assert folder.name == BEST_PRACTICE_MODELS_FOLDER
        assert folder.parent == Path(catalogue_module.__file__).resolve().parent
        assert (folder / README_NAME).is_file()

    def test_every_bundled_pair_loads(self, caplog: pytest.LogCaptureFixture) -> None:
        """A broken bundle fails here, not in a customer's assistant - and no description file is orphaned"""
        caplog.set_level(logging.ERROR, logger=CATALOGUE_LOGGER)
        folder = default_models_folder()

        catalogue = load_catalogue(folder)

        bundled_ids: set[str] = {model_id_of(path) for path in find_model_files(folder)}

        assert {model.model_id for model in catalogue.models} == bundled_ids
        assert not find_orphan_meta_files(folder)
        assert not [record.getMessage() for record in caplog.records if record.name == CATALOGUE_LOGGER]

    def test_the_bundled_catalogue_is_read_once(self) -> None:
        """The same object every time"""
        assert get_best_practice_catalogue() is get_best_practice_catalogue()
