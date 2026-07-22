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
import { Directive, DestroyRef, ElementRef, Input, OnInit, Renderer2, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

/**
 * Discovery gate for clickable hosts: keeps the element visible, adds a "Pro" badge while the feature
 * is locked, and intercepts activation (click / Enter) to open the upgrade modal instead of running
 * the host's own action. When the feature is unlocked the directive is completely inert.
 *
 *   <button [dgPremiumGate]="LicenseFeature.Ipam" (click)="openNetworks()">Networks</button>
 *
 * Use this for surfaces that should stay discoverable. For access surfaces that should disappear when
 * locked, use {@link PremiumFeatureDirective} (`*dgPremiumFeature`).
 */
@Directive({
  selector: '[dgPremiumGate]',
  standalone: true,
  host: {
    '(click)': 'onActivate($event)',
    '(keydown.enter)': 'onActivate($event)'
  }
})
export class PremiumGateDirective implements OnInit {

  @Input({ alias: 'dgPremiumGate', required: true }) feature!: LicenseFeature;

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly renderer = inject(Renderer2);
  private readonly premiumFeatureService = inject(PremiumFeatureService);
  private readonly destroyRef = inject(DestroyRef);

  private locked = false;
  private badge?: HTMLElement;

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.premiumFeatureService.isAvailable$(this.feature)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((available) => this.setLocked(!available));
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  onActivate(event: Event): void {
    if (!this.locked) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.premiumFeatureService.promptUpgrade(this.feature);
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private setLocked(locked: boolean): void {
    this.locked = locked;
    const element = this.host.nativeElement;

    if (locked) {
      this.renderer.addClass(element, 'dg-premium-locked');
      this.renderer.setAttribute(element, 'title', 'Premium feature');
      this.addBadge();
    } else {
      this.renderer.removeClass(element, 'dg-premium-locked');
      this.renderer.removeAttribute(element, 'title');
      this.removeBadge();
    }
  }

  private addBadge(): void {
    if (this.badge) {
      return;
    }

    const badge = this.renderer.createElement('span');
    this.renderer.addClass(badge, 'dg-premium-badge');
    this.renderer.setAttribute(badge, 'aria-label', 'Premium feature');
    this.renderer.appendChild(badge, this.renderer.createText('Pro'));
    this.renderer.appendChild(this.host.nativeElement, badge);
    this.badge = badge;
  }

  private removeBadge(): void {
    if (!this.badge) {
      return;
    }

    this.renderer.removeChild(this.host.nativeElement, this.badge);
    this.badge = undefined;
  }
}
