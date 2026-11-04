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
Unit tests for the best-practice repository sync (``best_practice_repository``)

GitHub is never asked: the download is driven with a stubbed ``requests.get`` and archives are built in memory
(``tests.utils.best_practice_repository_fixture``); the folder is ``tmp_path``. Pinned: which environment turns the sync
on and which is refused, the archive URL, that no message carries the token or a redirect's query string, the size
limits, which archive entries are model files, that the folder is mirrored exactly (added, updated, removed, other
files left alone), that an inconsistent model is logged, and that a failed sync is one WARNING and never raises
"""
import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from cmdb.errors.configuration_transfer import BestPracticeRepositoryError
from cmdb.framework.configuration_transfer import best_practice_repository as module
from cmdb.framework.configuration_transfer.best_practice_catalogue import repository_models_folder
from cmdb.framework.configuration_transfer.best_practice_constants import MODEL_FILE_ENCODING
from cmdb.framework.configuration_transfer.best_practice_repository import (
    RepositorySettings,
    RepositorySyncReport,
    archive_url,
    download_repository_archive,
    extract_model_files,
    hide_query_strings,
    log_model_problems,
    mirror_model_files,
    path_in_repository,
    read_limited,
    read_repository_settings,
    sync_best_practice_repository,
    write_file_atomically,
)
from cmdb.framework.configuration_transfer.best_practice_repository_constants import (
    BEARER_TOKEN,
    CONNECT_TIMEOUT_SECONDS,
    GITHUB_API_URL,
    HIDDEN_QUERY,
    MAX_ARCHIVE_BYTES,
    MAX_MODEL_FILE_BYTES,
    READ_TIMEOUT_SECONDS,
    BestPracticeRepositoryEnv,
    GitHubRequestHeader,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import TransferFileKey

from tests.utils.best_practice_model_fixture import model_document, model_meta
from tests.utils.best_practice_repository_fixture import REPOSITORY, TOKEN, build_archive, model_file_bytes
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ENV: str = BestPracticeRepositoryEnv.REPOSITORY.value
TOKEN_ENV: str = BestPracticeRepositoryEnv.TOKEN.value
REF_ENV: str = BestPracticeRepositoryEnv.REF.value
PATH_ENV: str = BestPracticeRepositoryEnv.PATH.value
ENVIRON: dict[str, str] = {REPO_ENV: REPOSITORY, TOKEN_ENV: TOKEN}
SETTINGS: RepositorySettings = RepositorySettings(repository=REPOSITORY, token=TOKEN)
MODELS_PATH: str = 'models'
FIRST_FILE: str = 'clients.json'
SECOND_FILE: str = 'network.json'
OTHER_FILE: str = 'notes.txt'
FIRST_CONTENT: bytes = b'{"first": 1}'
SECOND_CONTENT: bytes = b'{"second": 2}'
CHANGED_CONTENT: bytes = b'{"first": 2}'
REDIRECT_TOKEN: str = 'redirect-download-token'
REPOSITORY_LOGGER: str = module.LOGGER.name


def _response(status: int = 200, chunks: list[bytes] | None = None) -> MagicMock:
    """A streamed requests answer usable as a context manager"""
    response = MagicMock(status_code=status)
    response.iter_content.return_value = iter(chunks if chunks is not None else [b'archive'])
    response.__enter__.return_value = response
    return response


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The sync's WARNING messages"""
    return [record.getMessage() for record in caplog.records
            if record.name == REPOSITORY_LOGGER and record.levelno == logging.WARNING]


class TestReadRepositorySettings:
    """Which environment turns the sync on"""

    @pytest.mark.parametrize('environ', [{}, {REPO_ENV: ''}, {REPO_ENV: '  ', TOKEN_ENV: TOKEN}],
                             ids=['unset', 'empty', 'blank'])
    def test_without_a_repository_the_sync_is_off(self, environ: dict[str, str]) -> None:
        """None - not an error"""
        assert read_repository_settings(environ) is None

    def test_the_defaults(self) -> None:
        """Default branch, repository root, the public GitHub API"""
        settings = read_repository_settings(ENVIRON)

        assert settings == RepositorySettings(repository=REPOSITORY, token=TOKEN, ref='', path=PurePosixPath(),
                                              api_url=GITHUB_API_URL)

    def test_every_variable_is_read_and_trimmed(self) -> None:
        """The folder loses its outer slashes"""
        settings = read_repository_settings({REPO_ENV: f' {REPOSITORY} ', TOKEN_ENV: f' {TOKEN} ',
                                             REF_ENV: ' release/1.0 ', PATH_ENV: ' /models/cloud/ '})

        assert (settings.repository, settings.token, settings.ref, settings.path) == (
            REPOSITORY, TOKEN, 'release/1.0', PurePosixPath('models/cloud'))

    def test_the_api_url_is_taken_as_given(self) -> None:
        """For a stub in tests"""
        assert read_repository_settings(ENVIRON, 'http://127.0.0.1:1').api_url == 'http://127.0.0.1:1'

    @pytest.mark.parametrize('token', [None, '', '  '], ids=['unset', 'empty', 'blank'])
    def test_a_repository_without_a_token_is_refused(self, token: str | None) -> None:
        """Named by both variables"""
        environ: dict[str, str] = {REPO_ENV: REPOSITORY} if token is None else {REPO_ENV: REPOSITORY, TOKEN_ENV: token}

        with pytest.raises(BestPracticeRepositoryError, match=f'{TOKEN_ENV}.*{REPO_ENV}'):
            read_repository_settings(environ)

    @pytest.mark.parametrize('repository', ['acme', 'acme/models/extra', 'https://github.com/acme/models',
                                            'acme/mo dels'], ids=['no-owner', 'three-parts', 'url', 'space'])
    def test_a_misspelt_repository_is_refused(self, repository: str) -> None:
        """owner/repo only"""
        with pytest.raises(BestPracticeRepositoryError, match=REPO_ENV):
            read_repository_settings({REPO_ENV: repository, TOKEN_ENV: TOKEN})

    @pytest.mark.parametrize('path', ['..', 'models/../..', '../other'])
    def test_a_folder_leaving_the_repository_is_refused(self, path: str) -> None:
        """No '..' segment"""
        with pytest.raises(BestPracticeRepositoryError, match=PATH_ENV):
            read_repository_settings({**ENVIRON, PATH_ENV: path})

    def test_the_token_is_not_in_the_repr(self) -> None:
        """A logged settings object never shows it"""
        assert TOKEN not in repr(read_repository_settings(ENVIRON))


class TestArchiveUrl:
    """The tarball endpoint"""

    def test_without_a_ref_the_default_branch(self) -> None:
        """No ref segment"""
        assert archive_url(SETTINGS) == f'{GITHUB_API_URL}/repos/{REPOSITORY}/tarball'

    @pytest.mark.parametrize('ref, segment', [('main', 'main'), ('release/1.0', 'release/1.0'),
                                              ('v1 #2', 'v1%20%232')], ids=['branch', 'slash', 'quoted'])
    def test_the_ref_is_the_last_segment(self, ref: str, segment: str) -> None:
        """Quoted, slashes kept"""
        settings = RepositorySettings(repository=REPOSITORY, token=TOKEN, ref=ref)

        assert archive_url(settings) == f'{GITHUB_API_URL}/repos/{REPOSITORY}/tarball/{segment}'


def test_query_strings_are_hidden() -> None:
    """A redirect's temporary token never reaches the log"""
    text: str = (f"Max retries exceeded with url: /acme/models/legacy.tar.gz/refs/heads/main?token={REDIRECT_TOKEN} "
                 f"(Caused by 'x?y=1')")

    hidden: str = hide_query_strings(text)

    assert REDIRECT_TOKEN not in hidden
    assert f'main{HIDDEN_QUERY} (Caused by' in hidden


class TestDownload:
    """The archive request"""

    def test_reads_every_chunk(self) -> None:
        """Joined in order"""
        assert read_limited(_response(chunks=[b'ab', b'cd']), REPOSITORY) == b'abcd'

    def test_a_too_large_archive_is_refused(self) -> None:
        """Stopped once past the limit"""
        with pytest.raises(BestPracticeRepositoryError, match=str(MAX_ARCHIVE_BYTES)):
            read_limited(_response(chunks=[b'x' * MAX_ARCHIVE_BYTES, b'x']), REPOSITORY)

    def test_the_request(self) -> None:
        """The token as a Bearer header, streamed, both timeouts"""
        with patch.object(module.requests, 'get', return_value=_response(chunks=[b'tar'])) as get:
            assert download_repository_archive(SETTINGS) == b'tar'

        get.assert_called_once_with(
            archive_url(SETTINGS), stream=True, timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            headers={
                GitHubRequestHeader.ACCEPT.value: 'application/vnd.github+json',
                GitHubRequestHeader.AUTHORIZATION.value: BEARER_TOKEN.format(token=TOKEN),
                GitHubRequestHeader.API_VERSION.value: '2022-11-28',
            },
        )

    @pytest.mark.parametrize('status', [401, 404, 500])
    def test_another_status_is_refused(self, status: int) -> None:
        """Named in the message"""
        with patch.object(module.requests, 'get', return_value=_response(status=status)), \
             pytest.raises(BestPracticeRepositoryError, match=str(status)):
            download_repository_archive(SETTINGS)

    def test_an_unreachable_github_is_refused_without_the_query(self) -> None:
        """The redirect's token is hidden; the error carries the cause"""
        failure = requests.ConnectionError(f'url: /archive?token={REDIRECT_TOKEN}')

        with patch.object(module.requests, 'get', side_effect=failure), \
             pytest.raises(BestPracticeRepositoryError) as exc_info:
            download_repository_archive(SETTINGS)

        assert REDIRECT_TOKEN not in str(exc_info.value)
        assert 'ConnectionError' in str(exc_info.value)
        assert exc_info.value.__cause__ is failure


class TestExtractModelFiles:
    """Which archive entries are model files"""

    @pytest.mark.parametrize('member_name, expected', [
        ('root', None), ('root/a.json', PurePosixPath('a.json')),
        ('root/models/a.json', PurePosixPath('models/a.json')),
    ], ids=['the-root-folder', 'at-the-root', 'in-a-folder'])
    def test_the_path_below_the_archive_folder(self, member_name: str, expected: PurePosixPath | None) -> None:
        """GitHub's {owner}-{repo}-{sha} folder is dropped"""
        assert path_in_repository(member_name) == expected

    def test_only_the_json_files_directly_in_the_root(self) -> None:
        """Deeper files, other endings and folders are not models"""
        archive: bytes = build_archive({FIRST_FILE: FIRST_CONTENT, f'{MODELS_PATH}/{SECOND_FILE}': SECOND_CONTENT,
                                        OTHER_FILE: b'text', 'README.md': b'readme'})

        assert extract_model_files(archive, SETTINGS) == {FIRST_FILE: FIRST_CONTENT}

    def test_only_the_json_files_directly_in_the_configured_folder(self) -> None:
        """Neither the root's nor a subfolder's"""
        archive: bytes = build_archive({FIRST_FILE: FIRST_CONTENT, f'{MODELS_PATH}/{SECOND_FILE}': SECOND_CONTENT,
                                        f'{MODELS_PATH}/deeper/{FIRST_FILE}': FIRST_CONTENT})
        settings = RepositorySettings(repository=REPOSITORY, token=TOKEN, path=PurePosixPath(MODELS_PATH))

        assert extract_model_files(archive, settings) == {SECOND_FILE: SECOND_CONTENT}

    def test_a_link_is_skipped(self) -> None:
        """Never followed"""
        archive: bytes = build_archive({FIRST_FILE: FIRST_CONTENT}, links={SECOND_FILE: '/etc/passwd'})

        assert extract_model_files(archive, SETTINGS) == {FIRST_FILE: FIRST_CONTENT}

    def test_a_too_large_file_is_skipped_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """The others are kept"""
        caplog.set_level(logging.WARNING, logger=REPOSITORY_LOGGER)
        archive: bytes = build_archive({FIRST_FILE: FIRST_CONTENT, SECOND_FILE: b' ' * (MAX_MODEL_FILE_BYTES + 1)})

        assert extract_model_files(archive, SETTINGS) == {FIRST_FILE: FIRST_CONTENT}
        assert any(SECOND_FILE in message for message in _warnings(caplog))

    def test_an_empty_folder_holds_no_models(self) -> None:
        """Every model was removed from the repository"""
        assert not extract_model_files(build_archive({OTHER_FILE: b'text'}), SETTINGS)

    @pytest.mark.parametrize('archive', [b'not an archive', b''], ids=['garbage', 'empty'])
    def test_an_unreadable_archive_is_refused(self, archive: bytes) -> None:
        """Named by its repository"""
        with pytest.raises(BestPracticeRepositoryError, match=REPOSITORY):
            extract_model_files(archive, SETTINGS)


class TestMirrorModelFiles:
    """The folder is made exactly the repository's"""

    def test_a_missing_folder_is_created(self, tmp_path: Path) -> None:
        """Every file added"""
        folder: Path = tmp_path / 'repository'

        report = mirror_model_files(folder, {FIRST_FILE: FIRST_CONTENT, SECOND_FILE: SECOND_CONTENT})

        assert report == RepositorySyncReport(added=(FIRST_FILE, SECOND_FILE))
        assert (folder / FIRST_FILE).read_bytes() == FIRST_CONTENT
        assert (folder / SECOND_FILE).read_bytes() == SECOND_CONTENT

    def test_changed_rewritten_unchanged_kept_missing_removed(self, tmp_path: Path) -> None:
        """One of each"""
        (tmp_path / FIRST_FILE).write_bytes(FIRST_CONTENT)
        (tmp_path / SECOND_FILE).write_bytes(SECOND_CONTENT)
        (tmp_path / 'removed.json').write_bytes(b'{}')

        report = mirror_model_files(tmp_path, {FIRST_FILE: CHANGED_CONTENT, SECOND_FILE: SECOND_CONTENT,
                                               'new.json': b'{}'})

        assert report == RepositorySyncReport(added=('new.json',), updated=(FIRST_FILE,), removed=('removed.json',),
                                              unchanged=(SECOND_FILE,))
        assert (tmp_path / FIRST_FILE).read_bytes() == CHANGED_CONTENT
        assert sorted(path.name for path in tmp_path.iterdir()) == sorted([FIRST_FILE, SECOND_FILE, 'new.json'])

    def test_an_unchanged_file_is_not_written(self, tmp_path: Path) -> None:
        """Compared, not rewritten"""
        (tmp_path / FIRST_FILE).write_bytes(FIRST_CONTENT)

        with patch.object(module, 'write_file_atomically') as write:
            mirror_model_files(tmp_path, {FIRST_FILE: FIRST_CONTENT})

        write.assert_not_called()

    def test_files_that_are_no_model_files_are_left_alone(self, tmp_path: Path) -> None:
        """Only *.json files belong to the repository"""
        (tmp_path / OTHER_FILE).write_bytes(b'text')

        mirror_model_files(tmp_path, {})

        assert (tmp_path / OTHER_FILE).read_bytes() == b'text'

    def test_a_second_run_changes_nothing(self, tmp_path: Path) -> None:
        """Re-run safe"""
        files: dict[str, bytes] = {FIRST_FILE: FIRST_CONTENT}
        mirror_model_files(tmp_path, files)

        assert mirror_model_files(tmp_path, files) == RepositorySyncReport(unchanged=(FIRST_FILE,))

    def test_a_folder_that_cannot_be_written_is_refused(self, tmp_path: Path) -> None:
        """A file where the folder should be"""
        blocker: Path = tmp_path / 'repository'
        blocker.write_bytes(b'')

        with pytest.raises(BestPracticeRepositoryError, match='could not be written'):
            mirror_model_files(blocker, {FIRST_FILE: FIRST_CONTENT})

    def test_a_file_is_written_through_a_partial_name(self, tmp_path: Path) -> None:
        """No half-written model under its own name; nothing left behind"""
        target: Path = tmp_path / FIRST_FILE

        write_file_atomically(target, FIRST_CONTENT)

        assert [path.name for path in tmp_path.iterdir()] == [FIRST_FILE]
        assert target.read_bytes() == FIRST_CONTENT


def test_an_inconsistent_model_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Its meta describes a category it does not hold; a consistent one is not logged"""
    caplog.set_level(logging.ERROR, logger=REPOSITORY_LOGGER)
    meta: dict[str, Any] = {**model_meta(), 'category_descriptions': {'ghost_category': 'Not in the model'}}
    (tmp_path / 'broken_refs.json').write_text(
        json.dumps({**model_document(), TransferFileKey.META.value: meta}, default=str), encoding=MODEL_FILE_ENCODING,
    )
    (tmp_path / 'fine.json').write_bytes(model_file_bytes())

    log_model_problems(tmp_path)

    messages = [record.getMessage() for record in caplog.records if record.name == REPOSITORY_LOGGER]
    assert len(messages) == 1
    assert 'broken_refs' in messages[0] and 'ghost_category' in messages[0]


class TestSync:
    """The startup step"""

    def test_without_a_repository_nothing_is_asked(self, tmp_path: Path) -> None:
        """None, GitHub never asked, the folder untouched"""
        with patch.object(module, 'download_repository_archive') as download:
            assert sync_best_practice_repository(tmp_path / 'repository', environ={}) is None

        download.assert_not_called()
        assert not (tmp_path / 'repository').exists()

    def test_the_repository_is_mirrored(self, tmp_path: Path) -> None:
        """Downloaded with the environment's settings, mirrored, reported"""
        folder: Path = tmp_path / 'repository'
        content: bytes = model_file_bytes()
        archive: bytes = build_archive({FIRST_FILE: content})

        with patch.object(module, 'download_repository_archive', return_value=archive) as download:
            report = sync_best_practice_repository(folder, environ=ENVIRON, api_url='http://stub')

        assert download.call_args.args[0] == RepositorySettings(repository=REPOSITORY, token=TOKEN,
                                                                api_url='http://stub')
        assert report == RepositorySyncReport(added=(FIRST_FILE,))
        assert (folder / FIRST_FILE).read_bytes() == content

    @pytest.mark.parametrize('environ, download', [
        ({REPO_ENV: REPOSITORY}, None),
        (ENVIRON, BestPracticeRepositoryError('GitHub answered 404')),
        (ENVIRON, b'not an archive'),
    ], ids=['no-token', 'download-refused', 'unreadable-archive'])
    def test_a_failed_sync_is_one_warning_and_keeps_the_folder(self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                               environ: dict[str, str], download: Any) -> None:
        """Never raises; what the folder holds stays"""
        caplog.set_level(logging.WARNING, logger=REPOSITORY_LOGGER)
        (tmp_path / FIRST_FILE).write_bytes(FIRST_CONTENT)
        stub = MagicMock(side_effect=download) if isinstance(download, Exception) else MagicMock(return_value=download)

        with patch.object(module, 'download_repository_archive', stub):
            assert sync_best_practice_repository(tmp_path, environ=environ) is None

        assert len(_warnings(caplog)) == 1
        assert TOKEN not in _warnings(caplog)[0]
        assert (tmp_path / FIRST_FILE).read_bytes() == FIRST_CONTENT

    def test_the_default_folder_is_the_repository_subfolder(self) -> None:
        """Next to the bundled models"""
        with patch.object(module, 'mirror_model_files', return_value=RepositorySyncReport()) as mirror, \
             patch.object(module, 'download_repository_archive', return_value=build_archive({})):
            sync_best_practice_repository(environ=ENVIRON)

        assert mirror.call_args.args[0] == repository_models_folder()

    def test_the_default_environment_is_the_process_environment(self, monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
        """os.environ"""
        monkeypatch.delenv(REPO_ENV, raising=False)

        assert sync_best_practice_repository(tmp_path) is None
