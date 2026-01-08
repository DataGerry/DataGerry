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
import { Component, EventEmitter, Output, OnInit, ChangeDetectorRef } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { finalize } from 'rxjs';

@Component({
  selector: 'cmdb-external-object-selector-modal',
  templateUrl: './external-object-selector-modal.component.html',
  styleUrls: ['./external-object-selector-modal.component.scss'],
  standalone: false
})
export class ExternalObjectSelectorModalComponent implements OnInit {
  @Output() insertTemplate = new EventEmitter<string>();

  public typeIds: number[] = [];
  public selectedObject: RenderResult | null = null;
  public selectedField: any = null;
  public fieldOptions: any[] = [];
  public loading = false;

  constructor(
    public activeModal: NgbActiveModal,
    private typeService: TypeService,
    private loaderService: LoaderService
  ) {}

  ngOnInit(): void {
    // Fetch all type IDs so objects can be loaded by selector
    this.fetchTypeIds();
  }

  fetchTypeIds(): void {
    const params: any = { filter: '', limit: 0, sort: 'public_id', order: 1, page: 1 };
    this.loading = true;
    this.loaderService.show();
  
    this.typeService.getTypes(params)
      .pipe(
        finalize(() => {
          this.loading = false;
          this.loaderService.hide();
        })
      )
      .subscribe({
        next: (resp: APIGetMultiResponse<any>) => {
          const ids = (resp?.results || []).map((t: any) => t.public_id);
          this.typeIds = ids.length > 0 ? ids : [];
        },
        error: () => {
          this.typeIds = [];
        }
      });
  }
  

  onObjectSelectionChange(selectedObjects: RenderResult | RenderResult[] | null): void {
    if (selectedObjects) {
      if (Array.isArray(selectedObjects)) {
        // Multiple selection, but we only expect single selection
        this.selectedObject = selectedObjects.length > 0 ? selectedObjects[0] : null;
      } else {
        // Single selection
        this.selectedObject = selectedObjects;
      }
      this.updateFieldOptions();
      this.selectedField = null;
    } else {
      this.selectedObject = null;
      this.fieldOptions = [];
      this.selectedField = null;
    }
  }

  updateFieldOptions(): void {
    this.fieldOptions = [];
    
    // Add Public ID as first option
    this.fieldOptions.push({
      value: 'public_id',
      label: 'Public ID'
    });

    // Add object fields if available
    if (this.selectedObject && this.selectedObject.fields) {
      this.selectedObject.fields.forEach((field: any) => {
        this.fieldOptions.push({
          value: field.name,
          label: field.label || field.name,
          type: field.type
        });
      });
    }
  }

  onFieldSelectionChange(field: any): void {
    this.selectedField = field;
  }

  insert(): void {
    if (!this.selectedObject || !this.selectedField) {
      return;
    }

    const objectId = this.selectedObject.object_information.object_id;
    let template: string;

    if (this.selectedField.value === 'public_id') {
      template = `{{ object(${objectId}).public_id }}`;
    } else {
      template = `{{ object(${objectId}).fields['${this.selectedField.value}'] }}`;
    }

    this.insertTemplate.emit(template);
    this.activeModal.close();
  }

  cancel(): void {
    this.activeModal.dismiss();
  }
}

