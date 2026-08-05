import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-progress-bar',
  templateUrl: './progress-bar.component.html',
  styleUrls: ['./progress-bar.component.scss'],
  standalone: false
})
export class ProgressBarComponent {
  @Input() value = 0;
  @Input() height = 10;
  @Input() ariaLabel = 'Progress';

  get clampedValue(): number {
    if (typeof this.value !== 'number') {
      return 0;
    }
    return Math.min(100, Math.max(0, this.value));
  }
}