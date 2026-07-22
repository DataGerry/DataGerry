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
import { Directive, DestroyRef, Input, OnInit, TemplateRef, ViewContainerRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

/**
 * Structural gate that renders its content only while the given premium feature is unlocked for the
 * active edition, and removes it otherwise. Reacts to license changes (import/removal) live and
 * fails closed until the license is known, so gated content never flashes for Community users.
 *
 *   <section *dgPremiumFeature="LicenseFeature.Ipam"> … </section>
 *
 * Use this for access surfaces that should disappear when locked. For "show, but mark as Pro and
 * upsell on click", use {@link PremiumGateDirective} (`[dgPremiumGate]`).
 */
@Directive({
  selector: '[dgPremiumFeature]',
  standalone: true
})
export class PremiumFeatureDirective implements OnInit {

  @Input({ alias: 'dgPremiumFeature', required: true }) feature!: LicenseFeature;

  private readonly templateRef = inject(TemplateRef<unknown>);
  private readonly viewContainer = inject(ViewContainerRef);
  private readonly premiumFeatureService = inject(PremiumFeatureService);
  private readonly destroyRef = inject(DestroyRef);

  private rendered = false;

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.premiumFeatureService.isAvailable$(this.feature)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((available) => this.render(available));
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private render(available: boolean): void {
    if (available && !this.rendered) {
      this.viewContainer.createEmbeddedView(this.templateRef);
      this.rendered = true;
    } else if (!available && this.rendered) {
      this.viewContainer.clear();
      this.rendered = false;
    }
  }
}
