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
import {
    Component,
    forwardRef,
    Input,
    OnInit,
    EventEmitter,
    Output
  } from '@angular/core';
  import {
    ControlValueAccessor,
    NG_VALUE_ACCESSOR
  } from '@angular/forms';
  import { Subject } from 'rxjs';
  
  @Component({
    selector: 'app-form-select',
    templateUrl: './select.component.html',
    styleUrls: ['./select.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => SelectComponent),
            multi: true
        }
    ],
    standalone: false
})
  export class SelectComponent implements ControlValueAccessor, OnInit {
    /**
     * The label to be displayed above or alongside the select component
     */
    @Input() label: string = '';
  
    /**
     * The array of objects for the dropdown
     */
    @Input() items: any[] = [];
  
    /**
     * The property name of each item in items array for the label
     */
    @Input() bindLabel = 'name';
  
    /**
     * The property name of each item in items array for the value
     */
    @Input() bindValue = 'public_id';
  
    /**
     * Placeholder text
     */
    @Input() placeholder = 'Select...';
  
    /**
     * Whether multiple selection is allowed
     */
    @Input() multiple = false;
  
    /**
     * Whether the field is required (used for showing * near the label, etc.)
     */
    @Input() required = false;
  
    /**
     * For making the component read-only or disabled 
     */
    @Input() disabled = false;
  
    /** The internal data model */
    value: any = null;

    @Input() dropdownDirection?: 'bottom' | 'top' = 'bottom';

    @Input() groupBy?: string;

    /**
     * Show a "Select All / Deselect All" toggle inside the dropdown.
     * Only honored when `multiple` is true.
     */
    @Input() enableSelectAll = false;

    /**
     * Shows the dropdown's own spinner. Set it while a paginated host is fetching the next page.
     */
    @Input() loading = false;

    /**
     * Hand a Subject in to search server side: the typed term is pushed into it and the dropdown stops
     * filtering the options itself, so the host decides what `items` holds. Leave it unset for a fully
     * loaded list, which keeps the built-in filtering.
     */
    @Input() typeahead: Subject<string>;

    @Output() selectedItemChange = new EventEmitter<any>();

    /**
     * Emitted when the option list is scrolled to its end, so a host that loads its items page by
     * page can append the next one. Leave it unbound for a fully loaded list.
     */
    @Output() scrolledToEnd = new EventEmitter<void>();

  
    /**
     * These are callbacks for ControlValueAccessor
     */
    private onChange: (val: any) => void = () => {};
    public onTouched: () => void = () => {};
  
    constructor() {}
  
    ngOnInit(): void {}
  
    /**
     * 1) Called by the forms API to write to the view when programmatic
     *    changes from the model are requested.
     */
    writeValue(value: any): void {
      this.value = value;
    }
  
    /**
     * 2) Registers a callback function that should be called
     *    when the control's value changes in the UI.
     */
    registerOnChange(fn: any): void {
      this.onChange = fn;
    }
  
    /**
     * 3) Registers a callback function that should be called
     *    when the control receives a blur event.
     */
    registerOnTouched(fn: any): void {
      this.onTouched = fn;
    }
  
    /**
     * 4) Allows the forms API to disable the element
     */
    setDisabledState?(isDisabled: boolean): void {
      this.disabled = isDisabled;
    }
  
    /**
     * Custom 'change' handler triggered by the template
     */
    onValueChange(selectedValue: any) {
      let outputValue;
      if (this.multiple) {
        const selectedArray = Array.isArray(selectedValue) ? selectedValue : [];
        this.value = selectedArray.map((item: any) => item[this.bindValue]);
        outputValue = selectedArray;
      } else {
        this.value = selectedValue ? selectedValue[this.bindValue] : null;
        outputValue = selectedValue;
      }

      this.onChange(this.value); // Notify Angular forms API
      this.selectedItemChange.emit(outputValue);
      this.onTouched();
    }

    public get selectableItems(): any[] {
      return (this.items || []).filter(item => !item?.disabled);
    }

    public get showSelectAllToggle(): boolean {
      return this.multiple
        && this.enableSelectAll
        && !this.disabled
        && this.selectableItems.length > 0;
    }

    public get allSelectableSelected(): boolean {
      const selectable = this.selectableItems;
      if (selectable.length === 0) {
        return false;
      }
      const selectedValues = new Set(Array.isArray(this.value) ? this.value : []);
      return selectable.every(item => selectedValues.has(item[this.bindValue]));
    }

    /**
     * True when at least one selectable item is currently selected.
     * Drives the enabled state of the "Deselect All" action so the user can
     * clear a partial selection without having to select everything first.
     */
    public get hasSelection(): boolean {
      const selectable = this.selectableItems;
      if (selectable.length === 0) {
        return false;
      }
      const selectedValues = new Set(Array.isArray(this.value) ? this.value : []);
      return selectable.some(item => selectedValues.has(item[this.bindValue]));
    }

    public selectAll(): void {
      if (!this.showSelectAllToggle || this.allSelectableSelected) {
        return;
      }
      this.onValueChange([...this.selectableItems]);
    }

    public deselectAll(): void {
      if (!this.showSelectAllToggle || !this.hasSelection) {
        return;
      }
      this.onValueChange([]);
    }

    public toggleSelectAll(): void {
      if (!this.showSelectAllToggle) {
        return;
      }
      const nextSelection = this.allSelectableSelected ? [] : [...this.selectableItems];
      this.onValueChange(nextSelection);
    }
  }
  

