/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/


import { CmdbDao } from '../../../../framework/models/cmdb-dao';
import { FileMetadata } from './metadata';

export class FileElement implements CmdbDao {

  // a set of data that describes and gives information about other data.
  public readonly public_id: number;
  public readonly gridOutId: number;
  public filename: string;
  public metadata: FileMetadata;
  public size: number;
  public upload_date: any;
  public inProcess: boolean = false;
  public children: any[] = [];
  public hasSubFolders: boolean = false;

  public constructor(init?: Partial<FileElement>) {
    Object.assign(this, init);
  }
}

export class SelectedFileArray implements Object {
  files: FileElement[] = [];
  totalSize: number = 0;
}
