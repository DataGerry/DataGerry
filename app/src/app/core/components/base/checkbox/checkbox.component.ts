import { Component, Input, Output, EventEmitter } from "@angular/core";


@Component({
    selector: 'app-checkbox',
    templateUrl: './checkbox.component.html',
    standalone: false
})
export class CheckboxComponent {
  @Input() label = '';
  @Input() id?: string;
  @Input() disabled = false;
  @Input() checked = false;
  @Output() checkedChange = new EventEmitter<boolean>(); 

  onInputChange(event: Event) {
    const inputEl = event.target as HTMLInputElement;
    this.checkedChange.emit(inputEl.checked);
  }
}