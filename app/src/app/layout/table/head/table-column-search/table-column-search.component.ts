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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import {
  Component,
  inject,
  ChangeDetectionStrategy,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  ViewEncapsulation,
} from '@angular/core';
import { Column } from '../../table.types';
import { UntypedFormArray, UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ReplaySubject } from 'rxjs';
import { debounceTime, distinctUntilChanged, takeUntil } from 'rxjs/operators';

@Component({
    selector: 'thead[table-column-search]',
    templateUrl: './table-column-search.component.html',
    styleUrls: ['./table-column-search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    encapsulation: ViewEncapsulation.Emulated,
    standalone: false
})
export class TableColumnSearchComponent<T> implements OnInit, OnDestroy {

  /**
   * Component un subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Time debounce for search change emits.
   * Default time slot for change emits.
   * @private
   */
  private readonly debounceTime: number = 500;

  /**
   * Column search form group.
   */
  @Input() form: UntypedFormGroup;

  /**
   * Is row selected enabled.
   */
  @Input() selectEnabled: boolean = false;

  /**
   * Column setter.
   *
   * @param columns
   */
  @Input() columns: Array<Column>;

  /**
   * Event emitter when the search input changed.
   */
  @Output() public columnSearchChange: EventEmitter<any[]> = new EventEmitter<any[]>();

  private readonly fb = inject(UntypedFormBuilder);

  /**
   * Parse input field values
   * @param value string or boolean
   */
  public static maskRegex(value: string): string | boolean{
    try {
      if (typeof value === 'boolean') {
        return Boolean(JSON.parse(value));
      }
    } catch (e) {}
    return value.replace(/[.*+\-?^${}()|[\]\\]/g, '\\$&');
  }

  /**
   * OnInit of `TableColumnSearchComponent`.
   * Auto subscribes to search input control values changes.
   * Emits changes to columnSearchChange EventEmitter.
   */
  ngOnInit(): void {
    this.initColumnSearchForm();
    this.form.valueChanges.pipe(debounceTime(this.debounceTime), distinctUntilChanged(), takeUntil(this.subscriber))
      .subscribe(changes => {
        const validatedResults: any[] = [];
        for (const row of changes.rows) {
          const validatedRows: any[] = [];
          for (const key of Object.keys(row)){
            const validatedChange: Column = {name: '', type: 'text', data: ''};
            if (row[key]) {
              validatedChange.name = key;
              validatedChange.type = this.columns.find(c => c.name === key).type;
              const value = validatedChange.type === 'checkbox' ? 'unchecked' !== row[key] : row[key];
              validatedChange.data = TableColumnSearchComponent.maskRegex(value);
              if ('crossed' !== row[key]) {
                validatedRows.push(validatedChange);
              }
            }
          }
          if (validatedRows.length > 0) { validatedResults.push(validatedRows); }
        }
        this.columnSearchChange.emit(validatedResults);
      });
  }

  /**
   * Initialise form
   */
  private initColumnSearchForm() {
    this.form = this.fb.group({
      rows: this.fb.array([this.createItemFormGroup()])
    });
  }

  /**
   * Generate form controller from columns (dynamic)
   * @private
   */
  private createItemFormGroup(): UntypedFormGroup {
    const group: any = {};
    for (const c of this.columns) {
      if (c.hidden) { continue; }
      group[c.name] = '';
    }
    return this.fb.group(group);
  }

  /**
   * Get FormArray
   */
  public get rows() {
    return this.form.get('rows') as UntypedFormArray;
  }

  /**
   * Add new form controller
   */
  onAddRow() {
    this.rows.push(this.createItemFormGroup());
  }

  /**
   * Remove form controller at index
   */
  onRemoveRow(rowIndex: number){
    this.rows.removeAt(rowIndex);
  }

  public getController(name: string, level: number) {
    const group: any = this.form.controls.rows;
    return group.controls[level].controls[name];
  }

  /**
   *
   * @param name form control name
   * @param level form group control level
   * @private
   */
  public setState(name: string, level: number) {
    const control: any = this.getController(name, level);
    switch (control.value) {
      case '':
      case 'crossed': {
        control.setValue('checked');
        break;
      }
      case 'checked': {
        control.setValue('unchecked');
        break;
      }
      case 'unchecked': {
        control.setValue('crossed');
        break;
      }
    }
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
