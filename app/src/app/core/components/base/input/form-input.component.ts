import { Component, Input, forwardRef } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-form-input',
    templateUrl: './form-input.component.html',
    styleUrls: ['./form-input.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => FormInputComponent),
            multi: true
        }
    ],
    standalone: false
})
export class FormInputComponent implements ControlValueAccessor {
  @Input() label: string;
  @Input() placeholder: string = '';
  @Input() required: boolean = false;
  @Input() type: string = 'text';
  @Input() disabled: boolean = false;
  @Input() errorMessage: string = '';
  @Input() readonly: boolean = false;

  private innerValue: any = '';

  // ControlValueAccessor interface
  onChange: any = () => {};
  onTouched: any = () => {};

  set value(val: any) {
    if (val !== this.innerValue) {
      this.innerValue = val;
      this.onChange(val);
    }
  }

  get value(): any {
    return this.innerValue;
  }

  writeValue(value: any): void {
    this.innerValue = value;
  }

  registerOnChange(fn: any): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: any): void {
    this.onTouched = fn;
  }

  setDisabledState?(isDisabled: boolean): void {
    this.disabled = isDisabled;
  }

  // Template event handlers
  public onInput(event: Event): void {
    const target = event.target as HTMLInputElement;
    this.value = target.value;
  }

  public onBlur(): void {
    this.onTouched();
  }
}
