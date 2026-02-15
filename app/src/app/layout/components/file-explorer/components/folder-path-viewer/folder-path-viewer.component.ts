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

import { Component, Input, OnInit } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { FileElement } from '../../model/file-element';
import { FileService } from '../../service/file.service';

@Component({
    selector: 'cmdb-folder-path-viewer',
    templateUrl: './folder-path-viewer.component.html',
    styleUrls: ['./folder-path-viewer.component.scss'],
    standalone: false
})
export class FolderPathViewerComponent implements OnInit {

  public pathViewer: string[] = [];
  private selectedFileElement: any;

  @Input() folderTree: FileElement[] = [];
  @Input()
  set selectedFileFolder( value: BehaviorSubject<any>) {
    this.selectedFileElement = value;
  }

  get selectedFileFolder(): BehaviorSubject<any> {
    return this.selectedFileElement;
  }

  constructor(private fileService: FileService) {
  }

  public ngOnInit(): void {
    this.selectedFileFolder.subscribe(folder => {
      if (folder) {
        this.pathViewer = this.fileService.pathBuilder(folder.public_id, [], this.folderTree);
      }
    });
  }
}
