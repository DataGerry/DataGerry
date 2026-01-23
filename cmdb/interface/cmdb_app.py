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
Implementation of BaseCmdbApp
"""
import logging

from flask import Flask

from cmdb import __CLOUD_MODE__, __LOCAL_MODE__
from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  BaseCmdbApp - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseCmdbApp(Flask):
    """
    A base class for the CMDB application, extending Flask
    """
    def __init__(self, import_name: str, database_manager: MongoDatabaseManager | None = None) -> None:
        """
        Initializes the BaseCmdbApp instance

        Args:
            import_name (str): The name of the application module
            database_manager (MongoDatabaseManager | None, optional): Database interaction manager. Defaults to None
        """
        self.database_manager: MongoDatabaseManager | None = database_manager
        self.temp_folder = '/tmp/'
        self.cloud_mode: bool = __CLOUD_MODE__
        self.local_mode: bool = __LOCAL_MODE__

        # Used for local development
        self.asymmetric_key: dict[str, bytes] = {
            'private': (
                b"-----BEGIN RSA PRIVATE KEY-----\n"
                b"MIIEogIBAAKCAQEAmFEdxz3bGXnCYuKX2AFliOytBbsTrJWI/iLqzBX1EZSL0s1c\n"
                b"f+bFAez8fvpJRtlvlIpbj+a7v8REbgL6JsKVuT24SfadVb4UQOCtcPyWQSc0MPdY\n"
                b"qQM+4RpKGyHqoo48+EqkiTbtBNX39Vox5TilbDKgrcbsEd+J05H4dmIdu1do1aCg\n"
                b"bF/MHUo1vdgLMQXKz8aj9QAj9wy7PgpmUSQk5hT/eRl4TD+ZntnnI5L0FYU9LMS5\n"
                b"lyANGETs5LpmHBK/E9kwu9+cSwKwg2UQvxEiHov1gxome03Q9JRawXiz4oeWyAVh\n"
                b"n04w83C7HfUIJg3cSuuP9e95zLDqiloRmAzjuQIDAQABAoIBAA+swlohlhmDL6NW\n"
                b"Qw7YRvMOOziUod/QBDj2DjB6Pn4Eidaj6mXhsWrDMRFer7mOMRbJ3cYbdj0UBUBG\n"
                b"h2iDfB3D+aIH8nVTUjmCfarb3ZkfIBZ9b+b1xevrtQ5hgUhhB6p8IP5bdA0cOXAr\n"
                b"C+k1WQW/WIyFpP/qX6BRnG6PZpSjr5ka+o3TKHePU0LjQiI3VGj7bpuzQEmJ4OSp\n"
                b"CRRzkxHWJ/4BY8Mpb2NlWmvBUKwiz0R7w31awH+mRX2m+ne12uXblgsJpcrgsS2I\n"
                b"7EiXx+1oDeMKqWx/p3A1baXXH6iqAWUvA19E/NZDjxR8HuUgOaZK2phjzzJFyfGL\n"
                b"xqdJxHECgYEAunYcNFil6/tAftv0nhX2fanHn/kKufD1TTF8wahtclyXELD4FKTl\n"
                b"EOz4j6lx3mefF/rtFIyTpbVjGWEC6f0ZxHXloynMRht5NIjmgEJRTBmdGnn6mH7G\n"
                b"xf6pKkIviXxMzUQEqBqHSiWnPNWMzGgPErXrmCbDodfwScvq9j+NFZECgYEA0R8n\n"
                b"DzxPE1podpajBCKSb2hS0Bw1fKs/gFyxowcA/TGH7A1a8k0PMh/z5oGrSUGH5ny3\n"
                b"mtN9yBKYrTuDXVSKyycJI/CEJLsUQBFvl6Chi4yF2pc60adnnJIuSO1LpHNPLEFK\n"
                b"iSjUgVy6zg3BT2FuYuzWmTlYz34/4I1T3CYPt6kCgYBcdsOHxcoJ2p9iCUsltbh1\n"
                b"GmNO1h3WlUHflMHL+uzDQFz9PvTWr+qT2R9thlZcNsBzENDOVuPE0c0hwbTDOeq0\n"
                b"PM6yecC9p1QUlCrRwZE1DqKUhZaaVovVlXJn7UhLgmNHiwpQHk+mmkNzbGaU2qlW\n"
                b"2vXIjriGomGbBs8ua9dXsQKBgD8HnbU43zidEklUA9RWOz66+eLh7bkiwGQHDD9v\n"
                b"9/tYd3hNWjEXytG30cKTKLZOuxBcXNackhfAiyYDfwedWKv8mwOrFZkgjez1lGXm\n"
                b"M2qlMx78X+0bAN6vLKYsZ5UscBuNnlKS7OIEugUrHi231xaX/eJ25266xbP/xNvg\n"
                b"2PHpAoGAdvSh+sk0sND4psRcP/Gpx3ey+/BD6G4XQiewtvMJMNb5T9FnYoesU70Q\n"
                b"mQ7sp8eSTmvfyRNtHwUDdfCF+bycdc5aXiQSKZPlgA2sc5NyZ38g37En8PBAQqHC\n"
                b"qBfGj4rTzhS75P72w3isT06TocYd+ulWZVZPAlTV6T4WyWleWf4=\n"
                b"-----END RSA PRIVATE KEY-----"
            ),
            'public': (
                b"-----BEGIN PUBLIC KEY-----\n"
                b"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmFEdxz3bGXnCYuKX2AFl\n"
                b"iOytBbsTrJWI/iLqzBX1EZSL0s1cf+bFAez8fvpJRtlvlIpbj+a7v8REbgL6JsKV\n"
                b"uT24SfadVb4UQOCtcPyWQSc0MPdYqQM+4RpKGyHqoo48+EqkiTbtBNX39Vox5Til\n"
                b"bDKgrcbsEd+J05H4dmIdu1do1aCgbF/MHUo1vdgLMQXKz8aj9QAj9wy7PgpmUSQk\n"
                b"5hT/eRl4TD+ZntnnI5L0FYU9LMS5lyANGETs5LpmHBK/E9kwu9+cSwKwg2UQvxEi\n"
                b"Hov1gxome03Q9JRawXiz4oeWyAVhn04w83C7HfUIJg3cSuuP9e95zLDqiloRmAzj\n"
                b"uQIDAQAB\n"
                b"-----END PUBLIC KEY-----"
            ),
        }

        # Used for local development
        self.symmetric_key = (
            b'\x11\xeb\x8d*C\x95\xdd\xec0\xca7\x9ds\x92\xe9\x9b\x1e|i\x92i\x1c\x90\x8aw\xcd\x9aT\xbf\x1b)\x83'
        )

        super().__init__(import_name)
