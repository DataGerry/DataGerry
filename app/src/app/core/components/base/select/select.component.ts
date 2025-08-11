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

    @Output() selectedItemChange = new EventEmitter<any>();

  
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
        this.value = selectedValue.map((item: any) => item[this.bindValue]);
        outputValue = selectedValue;
      } else {
        this.value = selectedValue ? selectedValue[this.bindValue] : null;
        outputValue = selectedValue;
      }
      
      this.onChange(this.value); // Notify Angular forms API
      this.selectedItemChange.emit(outputValue);
      this.onTouched();
    }
  }
  

