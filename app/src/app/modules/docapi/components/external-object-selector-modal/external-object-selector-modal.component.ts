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
import { Component, EventEmitter, Output, OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { finalize } from 'rxjs';
import { TemplateHelperService } from 'src/app/settings/services/template-helper.service';

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
  public fieldMenuItems: any[] = [];
  public fieldMenuOpen = false;
  public activePath: any[] = [];
  public activeItems: any[] = [];
  public loading = false;

  constructor(
    public activeModal: NgbActiveModal,
    private typeService: TypeService,
    private loaderService: LoaderService,
    private templateHelperService: TemplateHelperService
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
      void this.updateFieldOptions();
      this.selectedField = null;
      this.fieldMenuOpen = false;
      this.activePath = [];
      this.activeItems = [];
    } else {
      this.selectedObject = null;
      this.fieldMenuItems = [];
      this.selectedField = null;
      this.fieldMenuOpen = false;
      this.activePath = [];
      this.activeItems = [];
    }
  }

  async updateFieldOptions(): Promise<void> {
    this.fieldMenuItems = [];

    if (!this.selectedObject) {
      return;
    }

    const objectId = this.selectedObject.object_information.object_id;
    const typeId = this.selectedObject.type_information.type_id;
    const helperData = await this.templateHelperService.getObjectTemplateHelperData(typeId, '', 3, 'OBJECT');
    const externalHelperData = this.mapExternalTemplateData(helperData, objectId);
    this.fieldMenuItems = externalHelperData;
    this.activePath = [];
    this.activeItems = [];
  }

  toggleFieldMenu(): void {
    this.fieldMenuOpen = !this.fieldMenuOpen;
    if (!this.fieldMenuOpen) {
      this.activePath = [];
      this.activeItems = [];
    }
  }

  onMenuItemClick(item: any, path: string[], event: MouseEvent): void {
    if (item?.subdata?.length) {
      event.preventDefault();
      event.stopPropagation();
      this.setActiveReference(item, path);
      return;
    }

    if (!item?.templatedata) {
      return;
    }

    this.selectedField = {
      label: this.buildSelectedLabel(path, item.label),
      template: item.templatedata,
      type: item.type
    };
    this.fieldMenuOpen = false;
    this.activePath = [];
    this.activeItems = [];
  }

  insert(): void {
    if (!this.selectedObject || !this.selectedField) {
      return;
    }

    const template = this.selectedField.template;
    if (!template) {
      return;
    }

    this.insertTemplate.emit(template);
    this.activeModal.close();
  }

  cancel(): void {
    this.activeModal.dismiss();
  }

  private mapExternalTemplateData(data: any[], objectId: number): any[] {
    return (data || []).map((item) => ({
      ...item,
      templatedata: this.mapExternalTemplate(item.templatedata, objectId),
      subdata: item.subdata ? this.mapExternalTemplateData(item.subdata, objectId) : undefined
    }));
  }

  private mapExternalTemplate(template: string, objectId: number): string {
    if (!template) {
      return template;
    }
    if (template === '{{id}}') {
      return `{{ object(${objectId}).public_id }}`;
    }
    if (template.startsWith('{{mds')) {
      return template.replace('{{mds', `{{ object(${objectId}).mds`);
    }
    if (template.startsWith('{{fields')) {
      return template.replace('{{fields', `{{ object(${objectId}).fields`);
    }
    return template;
  }

  private buildSelectedLabel(path: any[], label: string): string {
    if (!path?.length) {
      return label;
    }
    const labels = path.map((entry) => typeof entry === 'string' ? entry : entry?.label).filter(Boolean);
    return `${labels.join(' > ')} > ${label}`;
  }

  public setActiveReference(item: any, path: any[]): void {
    if (!item?.subdata?.length) {
      this.activePath = [];
      this.activeItems = [];
      return;
    }
    this.activePath = [...(path || []), item];
    this.activeItems = item.subdata;
  }

  public jumpToPathIndex(index: number): void {
    if (index < 0) {
      this.activePath = [];
      this.activeItems = [];
      return;
    }
    this.activePath = this.activePath.slice(0, index + 1);
    const last = this.activePath[this.activePath.length - 1];
    this.activeItems = last?.subdata || [];
  }
}
