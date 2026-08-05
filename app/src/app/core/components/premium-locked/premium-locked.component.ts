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
import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';

import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

/**
 * Reusable "locked feature" placeholder: a dimmed faux preview behind a lock, a short pitch and an
 * upgrade call-to-action. Drop it in wherever a premium area should stay discoverable but inert for
 * the current edition (e.g. the object-view Risk Assessments tab).
 *
 *   <cmdb-premium-locked [feature]="LicenseFeature.Isms" title="…" text="…"></cmdb-premium-locked>
 */
@Component({
  selector: 'cmdb-premium-locked',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dg-locked">
      <div class="dg-locked__preview" aria-hidden="true">
        <span class="dg-locked__line"></span>
        <span class="dg-locked__line"></span>
        <span class="dg-locked__line"></span>
      </div>
      <div class="dg-locked__overlay">
        <i class="fas fa-lock dg-locked__icon" aria-hidden="true"></i>
        <h3 class="dg-locked__title">{{ title }}</h3>
        @if (text) {
        <p class="dg-locked__text">{{ text }}</p>
        }
        <button type="button" class="dg-locked__btn" (click)="upgrade()">{{ actionLabel }}</button>
      </div>
    </div>
  `,
  styles: [`
    .dg-locked {
      position: relative;
      min-height: 220px;
      padding: 24px;
    }

    .dg-locked__preview {
      display: flex;
      flex-direction: column;
      gap: 14px;
      opacity: 0.3;
      filter: blur(0.5px);
      pointer-events: none;
    }

    .dg-locked__line {
      height: 14px;
      border-radius: 5px;
      background: #d1d5db;
    }

    .dg-locked__line:nth-child(1) { width: 70%; }
    .dg-locked__line:nth-child(2) { width: 90%; }
    .dg-locked__line:nth-child(3) { width: 55%; }

    .dg-locked__overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 24px;
      text-align: center;
    }

    .dg-locked__icon {
      font-size: 30px;
      color: #e94d18;
      margin-bottom: 4px;
    }

    .dg-locked__title {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      color: #2c3e50;
    }

    .dg-locked__text {
      margin: 0;
      max-width: 420px;
      font-size: 13px;
      line-height: 1.5;
      color: #5a6c7d;
    }

    .dg-locked__btn {
      margin-top: 10px;
      padding: 9px 20px;
      font-size: 13px;
      font-weight: 600;
      color: #fff;
      /* Deepened brand orange so the white label keeps a >= 4.5:1 ratio (WCAG AA). */
      background: #c83f0e;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s ease;
    }

    .dg-locked__btn:hover {
      background: #b3380c;
    }
  `]
})
export class PremiumLockedComponent {

  @Input({ required: true }) feature!: LicenseFeature;
  @Input() title = 'This is a Pro feature';
  @Input() text = '';
  @Input() actionLabel = 'Upgrade to unlock';

  private readonly premiumFeatureService = inject(PremiumFeatureService);

  upgrade(): void {
    this.premiumFeatureService.promptUpgrade(this.feature);
  }
}
