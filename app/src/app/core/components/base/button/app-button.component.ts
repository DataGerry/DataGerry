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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, Output, EventEmitter, OnInit } from '@angular/core';

@Component({
    selector: 'app-button',
    templateUrl: './app-button.component.html',
    styleUrls: ['./app-button.component.scss'],
    standalone: false
})
export class ButtonComponent implements OnInit {
  /**
   * Text shown on the button.
   */
  @Input() label: string = 'Button';

  /**
   * Set the HTML button type: 'submit', 'button', or 'reset'.
   * Default is 'button'.
   */
  @Input() type: 'button' | 'submit' | 'reset' = 'button';

  /**
   * Pass in any Bootstrap class(es) you like, e.g. 'btn-success', 'btn-secondary me-2'.
   * This will be applied along with the default 'btn' class.
   */
  @Input() bootstrapClass: string = 'btn-secondary';

  /**
   * If true, button is disabled.
   */
  @Input() disabled: boolean = false;

  /**
   * If true, button is disabled.
   */
  @Input() padding: string = '';

  /**
   * Optional icon class(es) rendered before the label, e.g. 'fa fa-expand'.
   * Leave empty for a text-only button.
   */
  @Input() icon: string = '';

  /**
   * Accessible name, mapped to aria-label. Required for icon-only buttons
   * (empty label) so screen readers can announce the action.
   */
  @Input() ariaLabel: string = '';

  /**
   * Native tooltip text, mapped to the title attribute.
   */
  @Input() title: string = '';

  /**
   * Toggle state for buttons that behave as a switch, mapped to aria-pressed.
   * Leave null for regular (non-toggle) buttons.
   */
  @Input() ariaPressed: boolean | null = null;


  /**
   * Emitted when the button is clicked (unless disabled).
   */
  @Output() clicked = new EventEmitter<void>();

  onClick(): void {
    if (!this.disabled) {
      this.clicked.emit();
    }
  }

  ngOnInit(): void {
    // Ensure the button has the 'btn' class by default
  }
}
