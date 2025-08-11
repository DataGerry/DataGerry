import { Component, Input, forwardRef } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-form-textarea',
    templateUrl: './form-textarea.component.html',
    styleUrls: ['./form-textarea.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => FormTextareaComponent),
            multi: true
        }
    ],
    standalone: false
})
export class FormTextareaComponent implements ControlValueAccessor {
  @Input() label: string;
  @Input() placeholder: string = '';
  @Input() required: boolean = false;
  @Input() disabled: boolean = false;
  @Input() rows: number = 4;  // default number of rows
  @Input() errorMessage: string = '';

  private innerValue: string = '';

  // ControlValueAccessor methods
  onChange: any = () => {};
  onTouched: any = () => {};

  set value(val: string) {
    if (val !== this.innerValue) {
      this.innerValue = val;
      this.onChange(val);
    }
  }

  get value(): string {
    return this.innerValue;
  }

  writeValue(value: string): void {
    this.innerValue = value || '';
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

  // Handler for the textarea's 'input' event
  public onInput(event: Event): void {
    const target = event.target as HTMLTextAreaElement;
    this.value = target.value;
  }

  public onBlur(): void {
    this.onTouched();
  }
}
