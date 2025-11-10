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

import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CmdbMode } from '../../../modes.enum';
import { UntypedFormGroup } from '@angular/forms';
import { RenderResult } from '../../../models/cmdb-render';
import { CmdbType } from '../../../models/cmdb-type';

@Component({
    selector: 'cmdb-object-bulk-change-editor',
    templateUrl: './object-bulk-change-editor.component.html',
    styleUrls: ['./object-bulk-change-editor.component.scss'],
    standalone: false
})
export class ObjectBulkChangeEditorComponent {

  /**
   * Form render mode.
   */
  public readonly mode: CmdbMode = CmdbMode.Bulk;

  /**
   * Form control
   */
  @Input() public changeForm: UntypedFormGroup = new UntypedFormGroup({});
  @Input() public renderForm: UntypedFormGroup = new UntypedFormGroup({});

  /**
   * Bulk deactivation.
   */
  public activeState: boolean = true;
  @Output() activeChange: EventEmitter<boolean> = new EventEmitter<boolean>();

  /**
   * Type instance of the bulk change element.
   */
  @Input() public type: CmdbType;

  filteredData: any;


  ngOnInit(): void {
    const filterMDSFields = this.type.render_meta.sections.filter(tp => tp.type !== 'multi-data-section').flatMap(field => field.fields)
    const filteredFields = this.type.fields.filter(field => filterMDSFields.includes(field.name))

    this.filteredData = {
      ...this.type,
      render_meta: {
        ...this.type.render_meta,
        sections: this.type.render_meta.sections.filter(section => section.type !== "multi-data-section")
      },
      fields: filteredFields
    };

  }

  /**
   * Get the field by its name from the type.
   * @param name
   */
  public getFieldByName(name: string) {
    return this.type.fields.find(field => field.name === name);
  }

  public onActiveChange(value: boolean): void {
    if (value === undefined) {
      this.renderForm.markAsPristine();
    } else { this.renderForm.markAsDirty(); }
    this.activeState = value;
    this.activeChange.emit(this.activeState);
  }
}
