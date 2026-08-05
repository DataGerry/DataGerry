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

import { ChangeDetectorRef, Component, Input, OnInit } from '@angular/core';
import { RenderFieldComponent } from '../components.fields';
import { formatDate } from '@angular/common';
import { NgbDateAdapter, NgbDateParserFormatter } from '@ng-bootstrap/ng-bootstrap';
import { NgbStringAdapter, CustomDateParserFormatter } from '../../../../settings/date-settings/date-settings-formatter.service';
import { takeUntil } from 'rxjs/operators';
import { DateSettingsService } from '../../../../settings/services/date-settings.service';
import { ReplaySubject } from 'rxjs';
import { CmdbMode } from 'src/app/framework/modes.enum';

@Component({
    selector: 'cmdb-date',
    templateUrl: './date.component.html',
    styleUrls: ['./date.component.scss'],
    providers: [
        { provide: NgbDateAdapter, useClass: NgbStringAdapter },
        { provide: NgbDateParserFormatter, useClass: CustomDateParserFormatter }
    ],
    standalone: false
})
export class DateComponent extends RenderFieldComponent implements OnInit {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public datePlaceholder = 'YYYY-MM-DD';

  public constructor(private dateSettingsService: DateSettingsService, private cdr: ChangeDetectorRef) {
    super();
  }

  ngOnInit(): void {
    
    const control = this.parentFormGroup.get(this.data.name);
    const initialValue = control?.value;
    
  
    // Handle empty string values
    if (initialValue === '') {
      control.setValue(null, { onlySelf: true });
    }
    
    // FIX: Convert backend date format to HTML date input format
    if (initialValue && this.mode === CmdbMode.Edit && control) {
      this.convertAndSetDateValue(control, initialValue);
    }
  
    // Subscribe to date settings
    this.dateSettingsService.getDateSettings().pipe(takeUntil(this.subscriber)).subscribe((dateSettings: any) => {
      this.datePlaceholder = dateSettings?.date_format || 'YYYY-MM-DD';
    });
  
    this.cdr.detectChanges();
  }

  /**
   * Convert various date formats to YYYY-MM-DD format for HTML date input
   */
  private convertAndSetDateValue(control: any, value: any): void {
    
    try {
      let date: Date;
      
      // Handle MongoDB date format
      if (value && value.$date) {
        date = new Date(value.$date);
      }
      // Handle ISO string
      else if (typeof value === 'string') {
        date = new Date(value);
      }
      // Handle Date object
      else if (value instanceof Date) {
        date = value;
      }
      else {
        return;
      }

      // Validate date
      if (isNaN(date.getTime())) {
        return;
      }

      // Convert to YYYY-MM-DD format
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      const formattedDate = `${year}-${month}-${day}`;

      
      // Update form control
      control.setValue(formattedDate, { emitEvent: false });
      
      // Force change detection
      this.cdr.detectChanges();
      
      
    } catch (error) {
    }
  }

  public get currentDate() {
    const currentDate = this.parentFormGroup.get(this.data.name).value;
    
    if (currentDate && currentDate.$date) {
      return new Date(currentDate.$date);
    }
    
    if (typeof currentDate === 'string') {
      return new Date(currentDate);
    }
    
    return currentDate;
  }

  public resetDate() {
    this.controller.setValue(null, { onlySelf: true });
    this.controller.reset();
    this.controller.markAsTouched();
    this.controller.markAsDirty();
  }

  public copyToClipboard() {
    const currentDate = this.currentDate;
    
    if (!currentDate) {
      return;
    }
    
    const selBox = document.createElement('textarea');
    selBox.value = formatDate(currentDate, 'dd/MM/yyyy', 'en-US');
    this.generateDataForClipboard(selBox);
  }

  onDblClick(event: MouseEvent) {
    const inputElement = event.target as HTMLInputElement;
    
    if (inputElement.type === 'date') {
      inputElement.type = 'text';
      setTimeout(() => {
        inputElement.select();
      });
    }
  }

  onFocusOut(event: FocusEvent) {
    const inputElement = event.target as HTMLInputElement;
    
    if (inputElement.type === 'text') {
      inputElement.type = 'date';
    }
  }
}