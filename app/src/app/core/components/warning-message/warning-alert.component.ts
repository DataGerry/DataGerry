import { Component, Input } from '@angular/core';

@Component({
    selector: 'app-warning-alert',
    templateUrl: './warning-alert.component.html',
    styleUrls: ['./warning-alert.component.scss'],
    standalone: false
})
export class WarningAlertComponent {
  @Input() iconClass: string = 'fas fa-exclamation-circle';
  @Input() title: string = 'Warning:';
  @Input() message: string = '';
}
