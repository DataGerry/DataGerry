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

import { Injectable, OnDestroy } from '@angular/core';
import { TypeService } from '../../framework/services/type.service';
import { TemplateHelpdataElement } from '../models/template-helpdata-element';
import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { CmdbType } from '../../framework/models/cmdb-type';

@Injectable({
  providedIn: 'root'
})
export class TemplateHelperService implements OnDestroy {

  private subscriber: ReplaySubject<void>;

  constructor(private typeService: TypeService) {
    this.subscriber = new ReplaySubject<void>();
  }

  private async getSectionReferenceType(typeID: number) {
    return this.typeService.getType(typeID).pipe(takeUntil(this.subscriber)).toPromise();
  }

  public async getObjectTemplateHelperData(typeId: number, prefix: string = '', iteration: number = 3) {
    const templateHelperData = [];
    templateHelperData.push(({
      label: 'Public ID',
      templatedata: (prefix ? '{{fields' + prefix + '[\'id\']}}' : '{{id}}')
    }) as TemplateHelpdataElement);
    await this.typeService.getType(typeId).subscribe({
      next: async (cmdbTypeObj) => {
    
      const multiDataSectionFieldsSet = new Set(
        cmdbTypeObj.render_meta.sections
          .filter(section => section.type === "multi-data-section")
          .flatMap(section => section.fields)
      );

      const filteredFields = cmdbTypeObj.fields.filter(field => !multiDataSectionFieldsSet.has(field.name));

      const updatedCmdbTypeObj = {
        ...cmdbTypeObj,
        fields: filteredFields,
      };

      for (const field of updatedCmdbTypeObj.fields) {
        if (field.type === 'ref' && iteration > 0) {
          const changedPrefix = (prefix ? prefix + '[\'fields\'][\'' + field.name + '\']' : '[\'' + field.name + '\']');
          let subdata;

          if (!isNaN(field.ref_types) && !Array.isArray(field.ref_types)) {
            await this.getObjectTemplateHelperData(field.ref_types, changedPrefix, iteration - 1).then(data => {
              subdata = data;
            });
          } else if (field.ref_types.length === 1) {
            await this.getObjectTemplateHelperData(field.ref_types[0], changedPrefix, iteration - 1).then(data => {
              subdata = data;
            });
          } else {
            subdata = [];
            await field.ref_types.forEach((type) => {
              this.getObjectTemplateHelperData(type, changedPrefix, iteration - 1).then(data => {
                subdata.push(({
                  label: 'ref_type ' + type,
                  subdata: data
                }));
              });
            });
          }

          templateHelperData.push(({
            label: field.label,
            subdata
          }) as TemplateHelpdataElement);
        } else if (field.type === 'ref-section-field') {
          const refSection = cmdbTypeObj.render_meta.sections.find(s => s.name === field.name.substring(0, field.name.length - 6));
          const changedPrefix = (prefix ? prefix + '[\'fields\'][\'' + field.name + '\']' : '[\'' + field.name + '\']');
          if (!refSection) {
            continue;
          }
          await this.getSectionReferenceType(refSection.reference.type_id).then((referenceType: CmdbType) => {
            const referenceFields: Array<TemplateHelpdataElement> = [];
            let referenceFieldNames: Array<string> = [];
            if (refSection.reference.selected_fields && refSection.reference.selected_fields.length > 0) {
              referenceFieldNames = refSection.reference.selected_fields;
            } else {
              const referenceTypeSection = referenceType.render_meta.sections.find(s => s.name === refSection.reference.section_name);
              if (referenceTypeSection) {
                referenceFieldNames = referenceTypeSection.fields;
              }
            }
            for (const refFieldName of referenceFieldNames) {
              const refField = referenceType.fields.find(f => f.name === refFieldName);
              if (refField) {
                referenceFields.push(({
                  label: refField.label,
                  templatedata: (changedPrefix ? '{{fields' + changedPrefix + '[\'fields\'][\'' + refField.name + '\']}}' : '{{fields[\'' + refField.name + '\']}}')
                }) as TemplateHelpdataElement);
              }
            }
            templateHelperData.push(({
              label: field.label,
              subdata: referenceFields
            }) as TemplateHelpdataElement);
          });
        } else {
          templateHelperData.push(({
            label: field.label,
            templatedata: (prefix ? '{{fields' + prefix + '[\'fields\'][\'' + field.name + '\']}}' : '{{fields[\'' + field.name + '\']}}')
          }) as TemplateHelpdataElement);
        }
      }
    },
    error: (error) => {
      console.error(error);
  }}
    );
    return templateHelperData;
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
