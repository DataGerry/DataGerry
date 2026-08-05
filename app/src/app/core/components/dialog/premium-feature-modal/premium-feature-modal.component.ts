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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, inject, Input, ViewEncapsulation } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

/** Dismiss reasons returned to the caller so it can react to the user's choice. */
export const PREMIUM_FEATURE_MODAL_RESULT = {
  upgrade: 'upgrade',
  later: 'later'
} as const;


@Component({
  selector: 'cmdb-premium-feature-modal',
  templateUrl: './premium-feature-modal.component.html',
  styleUrls: ['./premium-feature-modal.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None
})
export class PremiumFeatureModalComponent {

  /* ------------------------------------------------ INPUTS / STATE ------------------------------------------------ */

  @Input() title = '';
  @Input() subtitle = '';
  @Input() description = '';
  @Input() icon = 'fas fa-star';
  @Input() benefits: string[] = [];
  @Input() editionLabel = 'Self-Hosted';
  @Input() primaryActionLabel = 'Upgrade Edition';
  @Input() secondaryActionLabel = 'Maybe later';

  public readonly activeModal = inject(NgbActiveModal);

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  /** Confirms the upgrade intent; the caller resolves the navigation target. */
  onUpgrade(): void {
    this.activeModal.close(PREMIUM_FEATURE_MODAL_RESULT.upgrade);
  }

  /** Closes the modal without upgrading ("Maybe later", backdrop or the close button). */
  onDismiss(): void {
    this.activeModal.dismiss(PREMIUM_FEATURE_MODAL_RESULT.later);
  }
}
