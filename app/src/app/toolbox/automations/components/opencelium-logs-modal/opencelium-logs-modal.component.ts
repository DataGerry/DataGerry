import { Component, Input, ViewEncapsulation } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-opencelium-logs-modal',
  templateUrl: './opencelium-logs-modal.component.html',
  styleUrls: ['./opencelium-logs-modal.component.scss'],
  standalone: false,
  encapsulation: ViewEncapsulation.None
})
export class OpenCeliumLogsModalComponent {
  @Input() baseUrl = '';
  @Input() token = '';
  @Input() executionId: number | null = null;
  @Input() isFullscreen = false;
  @Input() onToggleFullscreen?: (next: boolean) => void;

  constructor(public activeModal: NgbActiveModal) {}

  toggleFullscreen(): void {
    this.isFullscreen = !this.isFullscreen;
    this.onToggleFullscreen?.(this.isFullscreen);
  }
}
