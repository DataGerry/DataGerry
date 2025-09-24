/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, OnDestroy, OnInit, Input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subject, takeUntil } from 'rxjs';
import { NetboxService } from '../../../services/netbox.service';
import { RenderResult } from '../../../models/cmdb-render';

@Component({
  selector: 'cmdb-rack-elevation',
  templateUrl: './rack-elevation.component.html',
  styleUrls: ['./rack-elevation.component.scss']
})
export class RackElevationComponent implements OnInit, OnDestroy {
  @Input() renderResult: RenderResult;
  public svgMarkup: SafeHtml | null = null;
  public isLoading = false;
  public hasError = false;
  public isCollapsed = true; // Initially collapsed
  public hasRackId = false; // Track if we have a valid rack ID

  private destroy$ = new Subject<void>();

  constructor(private netbox: NetboxService, private sanitizer: DomSanitizer) {}

  ngOnInit(): void {
    // Extract rack ID from the specific field name
    const rackId = this.extractRackIdFromRenderResult();
    
    // Only make API call if rack ID is found
    if (rackId !== null) {
      this.hasRackId = true;
      this.isLoading = true;
      this.netbox
        .getRackElevationSvg(rackId)
        .pipe(takeUntil(this.destroy$))
        .subscribe({
          next: (raw) => {
            // Ensure links open in a new tab and convert relative xlink hrefs to absolute demo.netbox.dev URLs
            let withTargets = raw.replaceAll('<a ', '<a target="_blank" ');
            withTargets = withTargets.replaceAll('xlink:href="/dcim/', 'xlink:href="https://demo.netbox.dev/dcim/');
            this.svgMarkup = this.sanitizer.bypassSecurityTrustHtml(withTargets);
            this.isLoading = false;
          },
          error: () => {
            this.hasError = true;
            this.isLoading = false;
          }
        });
    }
  }

  private extractRackIdFromRenderResult(): number | null {
    const targetFieldName = 'text-e303f08b-e4f3-4a59-a3c5-af2fe6dfbddc';
    
    if (!this.renderResult || !this.renderResult.fields) {
      return null;
    }

    const targetField = this.renderResult.fields.find(field => field.name === targetFieldName);
    
    if (!targetField || !targetField.value) {
      return null;
    }

    // Convert the value to a number
    const rackId = Number(targetField.value);
    if (isNaN(rackId)) {
      return null;
    }

    return rackId;
  }

  toggleCollapse(): void {
    this.isCollapsed = !this.isCollapsed;
  }

  ngOnDestroy(): void {
    this.netbox?.clearApiToken();
    this.destroy$.next();
    this.destroy$.complete();
  }
}
