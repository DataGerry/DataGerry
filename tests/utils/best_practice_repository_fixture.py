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
A GitHub repository archive for the best-practice repository sync's tests, built in memory

``build_archive`` writes a gzip-compressed tar the way GitHub's tarball endpoint does: every file under one
``{owner}-{repo}-{sha}`` folder. ``model_file_bytes`` is a model file's content as the repository holds it - the fixture
model of ``best_practice_model_fixture`` with its ``meta`` section filled in
"""
import io
import json
import tarfile
from typing import Any

from cmdb.database.json_codec import default
from cmdb.framework.configuration_transfer.best_practice_constants import MODEL_FILE_ENCODING
from cmdb.framework.configuration_transfer.configuration_transfer_constants import TransferFileKey

from tests.utils.best_practice_model_fixture import model_document, model_meta
# -------------------------------------------------------------------------------------------------------------------- #

# The folder GitHub puts every file of the archive under
ARCHIVE_ROOT: str = 'acme-best-practice-1a2b3c4'
REPOSITORY: str = 'acme/best-practice'
TOKEN: str = 'github_pat_test_secret_0123456789'


def build_archive(files: dict[str, bytes], links: dict[str, str] | None = None, root: str = ARCHIVE_ROOT) -> bytes:
    """
    A gzip-compressed tar holding ``files`` (repository path -> content) and symbolic ``links`` (path -> target)

    Args:
        files (dict[str, bytes]): The regular files, by their path inside the repository
        links (dict[str, str] | None): Symbolic links, by their path inside the repository
        root (str): The folder every entry is put under

    Returns:
        bytes: The archive
    """
    buffer = io.BytesIO()

    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        folder = tarfile.TarInfo(root)
        folder.type = tarfile.DIRTYPE
        tar.addfile(folder)

        for path, content in files.items():
            member = tarfile.TarInfo(f'{root}/{path}')
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))

        for path, target in (links or {}).items():
            member = tarfile.TarInfo(f'{root}/{path}')
            member.type = tarfile.SYMTYPE
            member.linkname = target
            tar.addfile(member)

    return buffer.getvalue()


def model_file_bytes(title: str = 'Fixture model', order: int = 0, document: dict[str, Any] | None = None) -> bytes:
    """
    A model file's content: the fixture model with its meta section filled in

    Args:
        title (str): The model's title
        order (int): Its card order
        document (dict[str, Any] | None): The transfer file. Defaults to the fixture model

    Returns:
        bytes: The file's content
    """
    written: dict[str, Any] = {**(model_document() if document is None else document),
                               TransferFileKey.META.value: model_meta(title=title, order=order)}

    return json.dumps(written, default=default).encode(MODEL_FILE_ENCODING)
