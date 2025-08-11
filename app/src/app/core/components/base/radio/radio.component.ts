import {
    Component, Input, forwardRef
  } from '@angular/core';
  import {
    ControlValueAccessor, NG_VALUE_ACCESSOR
  } from '@angular/forms';
  
  @Component({
    selector: 'app-radio',
    templateUrl: './radio.component.html',
    styleUrls: ['./radio.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => RadioComponent),
            multi: true
        }
    ],
    standalone: false
})
  export class RadioComponent implements ControlValueAccessor {
    @Input() label: string;
    @Input() value: any;
    @Input() name: string;   // important for grouping
    @Input() disabled = false;
    @Input() id?: string;
  
    public innerValue: any;
  
    private onChange: (val: any) => void;
    private onTouched: () => void;
  
    registerOnChange(fn: (val: any) => void): void {
      this.onChange = fn;
    }
  
    registerOnTouched(fn: () => void): void {
      this.onTouched = fn;
    }
  
    setDisabledState(isDisabled: boolean): void {
      this.disabled = isDisabled;
    }
  
    writeValue(value: any): void {
      this.innerValue = value;
    }
  
    onInputChange(): void {
      if (this.onChange) {
        this.onChange(this.value);
      }
      if (this.onTouched) {
        this.onTouched();
      }
    }
  
    isChecked(): boolean {
      return this.innerValue === this.value;
    }
  }
  