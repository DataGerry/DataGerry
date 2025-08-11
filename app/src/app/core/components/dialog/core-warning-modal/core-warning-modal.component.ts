import { Component, Input } from '@angular/core';
import { Router } from '@angular/router';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
    selector: 'core-warning-modal',
    templateUrl: './core-warning-modal.component.html',
    standalone: false
})
export class CoreWarningModalComponent {
  @Input() title: string = 'Attention';
  @Input() message: string;
  @Input() confirmLabel: string;
  @Input() cancelLabel: string = 'Close';
  @Input() warningTitle: string = 'Warning:';
  @Input() warningIconClass: string = 'fas fa-exclamation-circle';
  @Input() route: string;

  constructor(public activeModal: NgbActiveModal, private router: Router) {}

  navigate(): void {
    this.activeModal.close('confirmed');
    if (this.route) {
      this.router.navigate([this.route]);
    }
  }

  cancel(): void {
    this.activeModal.dismiss('cancelled');
  }
}
