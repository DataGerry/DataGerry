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
import { ChangeDetectionStrategy, Component, computed, effect, input, isDevMode, output } from '@angular/core';

import {
    ButtonIconPosition,
    ButtonSize,
    ButtonTone,
    ButtonType,
    ButtonVariant
} from './app-button.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The single button of the product.
 *
 * Emphasis and meaning are separate inputs: `variant` decides how filled the button is,
 * `tone` decides what it means. Layout is never the button's job — spacing comes from a
 * flex `gap` on the surrounding toolbar or footer.
 */
@Component({
    selector: 'app-button',
    templateUrl: './app-button.component.html',
    styleUrls: ['./app-button.component.scss'],
    standalone: false,
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[attr.data-block]': 'block() ? "true" : null'
    }
})
export class ButtonComponent implements OnInit {
    }
})
export class ButtonComponent {

    /** Text shown on the button. Leave empty together with `icon` for an icon-only button. */
    readonly label = input<string>('');

    /** Emphasis. Defaults to the quietest sensible choice. */
    readonly variant = input<ButtonVariant>('outline');

    /** Meaning. Also drives the focus-ring hue. */
    readonly tone = input<ButtonTone>('neutral');

    /** Size step: sets height, padding, type size, radius and icon size together. */
    readonly size = input<ButtonSize>('md');

    /** Font Awesome class(es) rendered beside the label, e.g. 'fas fa-plus'. */
    readonly icon = input<string>('');

    readonly iconPosition = input<ButtonIconPosition>('start');

    /** Swaps the icon for a spinner, marks the button busy and blocks activation. */
    readonly loading = input<boolean>(false);

    /** Optional label shown while `loading` is true, e.g. 'Saving…'. */
    readonly loadingText = input<string>('');

    /** Full width of its container. */
    readonly block = input<boolean>(false);

    /** Fully rounded ends. */
    readonly pill = input<boolean>(false);

    readonly disabled = input<boolean>(false);

    readonly type = input<ButtonType>('button');

    /** Accessible name. Required for icon-only buttons. */
    readonly ariaLabel = input<string>('');

    /** Native tooltip text, mapped to the title attribute. */
    readonly title = input<string>('');

    /** Toggle state for buttons that behave as a switch. Leave null for regular buttons. */
    readonly ariaPressed = input<boolean | null>(null);

    /** Expanded state for buttons that reveal or hide a region. Leave null for regular buttons. */
    readonly ariaExpanded = input<boolean | null>(null);

    /** Id of the region this button controls, for dropdown and disclosure triggers. */
    readonly ariaControls = input<string>('');

    /** Popup kind this button opens, e.g. 'menu' or 'dialog'. */
    readonly ariaHasPopup = input<string>('');

    /** Emitted on activation, unless the button is disabled or loading. */
    readonly clicked = output<void>();

    readonly isIconOnly = computed(() => !this.label() && !!this.icon());

    readonly displayLabel = computed(() =>
        this.loading() ? this.loadingText() || this.label() : this.label()
    );

    readonly accessibleName = computed(() => this.ariaLabel() || this.title() || null);

    readonly isInactive = computed(() => this.disabled() || this.loading());

    readonly buttonClass = computed(() => {
        const classes = [
            'dg-button',
            `dg-button--${ this.variant() }`,
            `dg-button--${ this.tone() }`,
            `dg-button--${ this.size() }`
        ];

        if (this.isIconOnly()) {
            classes.push('dg-button--icon-only');
        }

        if (this.pill()) {
            classes.push('dg-button--pill');
        }

        if (this.loading()) {
            classes.push('dg-button--loading');
        }

        return classes.join(' ');
    });

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // Guarded here rather than inside the effect so production creates no effect at all —
        // there can be hundreds of buttons on a page.
        if (isDevMode()) {
            effect(() => {
                if (this.isIconOnly() && !this.accessibleName()) {
                    console.error(
                        '[app-button] An icon-only button needs an ariaLabel so screen readers ' +
                        `can announce it. Icon: "${ this.icon() }".`
                    );
                }
            });
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    onClick(): void {
        if (this.isInactive()) {
            return;
        }

        this.clicked.emit();
    }
}
