/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Component({
    selector: 'app-object-selector',
    templateUrl: './object-selector.component.html',
    styleUrls: ['./object-selector.component.scss'],
    standalone: false
})
export class ObjectSelectorComponent implements OnInit {
  @Input() typeIds: number[] = [];
  @Input() multiple = false;
  @Input() selectedIds: any[] = [];
  @Input() isViewMode = false;
  @Output() selectionChange = new EventEmitter<number[]>();

  public objectList: RenderResult[] = [];
  public selectedObjects: RenderResult[] | RenderResult | null = null; // Updated type
  public isLoading$ = this.loaderService.isLoading$;
  private params: CollectionParameters = null;

  constructor(
    private objectService: ObjectService,
    private loaderService: LoaderService,
    private toast: ToastService
  ) {}

  ngOnInit(): void {
    this.fetchObjects();
  }

  private fetchObjects(): void {
    if (!this.typeIds || this.typeIds.length === 0) {
      this.initSelectedObjects();
      return;
    }


    const filters: any[] = [{ $match: { type_id: { $in: this.typeIds } } }];
    if (this.isViewMode && this.selectedIds?.length) {
      filters.push({ $match: { public_id: { $in: this.selectedIds } } });
    }

    this.params = {
      filter: filters,
      projection: {
        'object_information.object_id': 1,
        'object_information.public_id': 1,
        'summary_line': 1,
        'type_information': 1
      },
      limit: 0,
      sort: 'public_id',
      order: 1,
      page: 1
    };

    this.loaderService.show();
    this.objectService.getObjects(this.params).pipe(finalize(() => this.loaderService.hide())).subscribe({
      next: (response: APIGetMultiResponse<RenderResult>) => {
        this.objectList = response.results || [];
        this.initSelectedObjects();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.objectList = [];
        this.initSelectedObjects();
      }
    });
  }

  private initSelectedObjects(): void {
    const numericIds: number[] = (this.selectedIds || []).map(item => {
      if (typeof item === 'number') {
        return item;
      } else if (item && item.object_information?.object_id) {
        return item.object_information.object_id;
      }
      return null;
    }).filter(x => x !== null) as number[];

    if (this.multiple) {
      this.selectedObjects = this.objectList.filter(obj =>
        numericIds.includes(obj.object_information.object_id)
      );
    } else {
      const id = numericIds[0]; // Take the first ID for single selection
      this.selectedObjects = id ? this.objectList.find(obj => obj.object_information.object_id === id) || null : null;
    }
  }

  public onSelectionChange(selectedValue: RenderResult | RenderResult[] | null): void {
    // Case 1: selectedValue is null or undefined
    if (!selectedValue) {
      this.selectedObjects = this.multiple ? [] : null;
      this.selectionChange.emit([]);
      return;
    }
  
    // Case 2: Multiple selection (expecting an array)
    if (this.multiple) {
      if (Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult[]
        const idArray = selectedValue.map(obj => obj.object_information.object_id);
        this.selectionChange.emit(idArray);
      } else {
        console.error('Expected an array for multiple selection, but got a single object');
      }
    }
    // Case 3: Single selection (expecting a single object)
    else {
      if (!Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult
        this.selectionChange.emit([selectedValue.object_information.object_id]);
      } else {
        console.error('Expected a single object for single selection, but got an array');
      }
    }
  }

  public groupByFn = (item: RenderResult) => item.type_information.type_label;
  public groupValueFn = (_: string, children: RenderResult[]) => ({
    name: children[0].type_information.type_label,
    total: children.length
  });
}