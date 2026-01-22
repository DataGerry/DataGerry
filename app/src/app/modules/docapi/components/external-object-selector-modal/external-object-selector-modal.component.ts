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
import { finalize, firstValueFrom } from 'rxjs';
import { ObjectService } from 'src/app/framework/services/object.service';

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
  private objectCache = new Map<number, RenderResult>();

  constructor(
    public activeModal: NgbActiveModal,
    private typeService: TypeService,
    private loaderService: LoaderService,
    private objectService: ObjectService<RenderResult>
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

    const rootObjectId = this.selectedObject.object_information?.object_id;
    if (!rootObjectId) {
      return;
    }
    this.fieldMenuItems = await this.buildMenuForRenderObject(this.selectedObject, 3, rootObjectId, ['fields'], true);
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


  private async buildMenuForRenderObject(
    object: RenderResult,
    depth: number,
    rootObjectId: number,
    baseSegments: string[],
    includePublicId: boolean,
    refPublicIdSegments?: string[]
  ): Promise<any[]> {
    const items = [];
    const objectId = object?.object_information?.object_id;
    if (!objectId) {
      return items;
    }

    if (includePublicId) {
      items.push({
        label: 'Public ID',
        templatedata: refPublicIdSegments
          ? this.buildObjectTemplate(rootObjectId, refPublicIdSegments)
          : this.buildObjectTemplate(rootObjectId, ['public_id']),
        name: 'public_id',
        type: 'public_id'
      });
    }

    const fields = Array.isArray(object.fields) ? object.fields : [];
    const sections = Array.isArray(object.sections) ? object.sections : [];
    const fieldByName = new Map<string, any>();
    const groupedFieldNames = new Set<string>();

    fields.forEach((field: any) => {
      if (field?.name) {
        fieldByName.set(field.name, field);
      }
    });

    const buildFieldMenuItem = async (field: any, segments: string[]): Promise<any | null> => {
      const fieldType = field?.type;
      if (fieldType === 'ref' || fieldType === 'ref-section-field') {
        const subdata = await this.buildReferenceSubmenu(field, depth - 1, rootObjectId, segments);
        if (subdata.length === 0) {
          return null;
        }
        return {
          label: field.label || field.name,
          subdata,
          name: field.name,
          type: field.type
        };
      }

      return {
        label: field.label || field.name,
        templatedata: this.buildObjectTemplate(rootObjectId, [...segments, field.name]),
        name: field.name,
        type: field.type
      };
    };

    const addSectionGroup = (labelBase: string, sectionItems: any[], name?: string, type?: string) => {
      if (!sectionItems.length) {
        return;
      }
      items.push({
        label: `[${sectionItems.length}] ${labelBase}`,
        subdata: sectionItems,
        name,
        type
      });
    };

    for (const section of sections) {
      const sectionFields = Array.isArray(section?.fields) ? section.fields : [];
      const sectionLabel = section?.label || section?.name || 'Section';
      const sectionType = section?.type;

      sectionFields.forEach((fieldName: string) => groupedFieldNames.add(fieldName));

      if (sectionType === 'multi-data-section') {
        const sectionItems = [];
        const mdsSegments = this.buildMdsSegments(baseSegments);

        for (const fieldName of sectionFields) {
          const field = fieldByName.get(fieldName);
          if (!field) {
            continue;
          }
          if (field.type === 'ref' || field.type === 'ref-section-field') {
            continue;
          }
          sectionItems.push({
            label: field.label || field.name,
            templatedata: this.buildObjectTemplate(rootObjectId, [...mdsSegments, section.name, field.name]),
            name: field.name,
            type: field.type
          });
        }

        addSectionGroup(sectionLabel, sectionItems, section?.name, 'multi-data-section');
        continue;
      }

      const sectionItems = [];
      for (const fieldName of sectionFields) {
        const field = fieldByName.get(fieldName);
        if (!field) {
          continue;
        }
        const item = await buildFieldMenuItem(field, baseSegments);
        if (item) {
          sectionItems.push(item);
        }
      }

      addSectionGroup(sectionLabel, sectionItems, section?.name, sectionType);
    }

    const otherItems = [];
    for (const field of fields) {
      if (!field?.name || groupedFieldNames.has(field.name)) {
        continue;
      }
      const item = await buildFieldMenuItem(field, baseSegments);
      if (item) {
        otherItems.push(item);
      }
    }

    addSectionGroup('Other Fields', otherItems, 'other-fields', 'other');

    return items;
  }


  private async buildReferenceSubmenu(
    field: any,
    depth: number,
    rootObjectId: number,
    baseSegments: string[]
  ): Promise<any[]> {
    if (!field?.value || depth < 0) {
      return [];
    }

    const referenced = await this.getRenderObject(field.value);
    if (!referenced) {
      return [];
    }

    if (field.type === 'ref-section-field') {
      const referenceFields = field?.references?.fields || [];
      const nextBaseSegments = [...baseSegments, field.name, 'fields'];
      return this.buildMenuFromReferenceFields(referenced, referenceFields, depth, rootObjectId, nextBaseSegments);
    }

    const nextBaseSegments = [...baseSegments, field.name, 'fields'];
    const publicIdSegments = [...baseSegments, field.name, 'public_id'];
    return this.buildMenuForRenderObject(
      referenced,
      depth,
      rootObjectId,
      nextBaseSegments,
      true,
      publicIdSegments
    );
  }


  private async buildMenuFromReferenceFields(
    object: RenderResult,
    referenceFields: any[],
    depth: number,
    rootObjectId: number,
    baseSegments: string[]
  ): Promise<any[]> {
    const items = [];
    const objectId = object?.object_information?.object_id;
    if (!objectId) {
      return items;
    }

    for (const refFieldDef of referenceFields) {
      const actualField = (object.fields || []).find((f) => f.name === refFieldDef.name) || refFieldDef;
      const fieldType = actualField?.type;

      if (fieldType === 'ref' || fieldType === 'ref-section-field') {
        const subdata = await this.buildReferenceSubmenu(actualField, depth - 1, rootObjectId, baseSegments);
        if (subdata.length === 0) {
          continue;
        }
        items.push({
          label: actualField.label || actualField.name,
          subdata,
          name: actualField.name,
          type: fieldType
        });
        continue;
      }

      items.push({
        label: refFieldDef.label || refFieldDef.name,
        templatedata: this.buildObjectTemplate(rootObjectId, [...baseSegments, refFieldDef.name]),
        name: refFieldDef.name,
        type: refFieldDef.type
      });
    }

    return items;
  }


  private buildObjectTemplate(rootObjectId: number, segments: string[]): string {
    const path = segments.map((segment, index) => {
      if (index === 0 && (segment === 'fields' || segment === 'mds')) {
        return `.${segment}`;
      }
      return `['${segment}']`;
    }).join('');
    return `{{ object(${rootObjectId})${path} }}`;
  }


  private buildMdsSegments(baseSegments: string[]): string[] {
    if (!baseSegments?.length) {
      return ['mds'];
    }
    const segments = [...baseSegments];
    if (segments[segments.length - 1] === 'fields') {
      segments[segments.length - 1] = 'mds';
    } else {
      segments.push('mds');
    }
    return segments;
  }


  private async getRenderObject(objectId: number): Promise<RenderResult | null> {
    if (!objectId) {
      return null;
    }
    if (this.objectCache.has(objectId)) {
      return this.objectCache.get(objectId) || null;
    }
    try {
      const renderObject = await firstValueFrom(this.objectService.getObject<RenderResult>(objectId));
      if (renderObject) {
        this.objectCache.set(objectId, renderObject);
      }
      return renderObject || null;
    } catch (error) {
      return null;
    }
  }
}
