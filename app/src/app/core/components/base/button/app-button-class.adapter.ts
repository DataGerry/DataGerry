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
import { ButtonSize, ButtonTone, ResolvedButtonStyle } from './app-button.types';

/**
 * Translates the Bootstrap class strings still passed through `app-button`'s deprecated
 * `bootstrapClass` input into the variant/tone/size the button should render as.
 *
 * Only the tokens mapped below are recognised; anything else is discarded rather than
 * forwarded to the DOM, so a caller cannot inject arbitrary classes through the component.
 * Delete this file once every call site passes variant/tone/size directly.
 */

const STYLE_BY_CLASS: Readonly<Record<string, ResolvedButtonStyle>> = {
    /* Filled — the primary action. Green is retired as an action colour: Save, Add and
       Submit are brand actions, so btn-success resolves to brand, not success. */
    'btn-primary': { variant: 'solid', tone: 'brand' },
    'btn-cmdb-primary': { variant: 'solid', tone: 'brand' },
    'btn-success': { variant: 'solid', tone: 'brand' },
    'btn-danger': { variant: 'solid', tone: 'danger' },

    /* Neutral. btn-secondary and btn-warning both resolve to #fbba00 today and are used
       for Cancel, Close and dropdown triggers rather than for warnings. */
    'btn-secondary': { variant: 'outline', tone: 'neutral' },
    'btn-warning': { variant: 'outline', tone: 'neutral' },
    'btn-outline-secondary': { variant: 'outline', tone: 'neutral' },
    'btn-outline-dark': { variant: 'outline', tone: 'neutral' },
    'btn-light': { variant: 'ghost', tone: 'neutral' },

    /* Bordered */
    'btn-outline-primary': { variant: 'outline', tone: 'brand' },
    'btn-outline-cmdb-primary': { variant: 'outline', tone: 'brand' },
    'btn-outline-danger': { variant: 'outline', tone: 'danger' },
    'btn-outline-success': { variant: 'outline', tone: 'success' },

    'btn-link': { variant: 'link', tone: 'brand' },

    /* The rack views reinvented these locally; fold them back into the system. */
    'rack-btn--primary': { variant: 'solid', tone: 'brand' },
    'rack-btn--danger': { variant: 'ghost', tone: 'danger' },
    'rack-btn--quiet': { variant: 'ghost', tone: 'neutral' }
};

const SIZE_BY_CLASS: Readonly<Record<string, ButtonSize>> = {
    'btn-sm': 'sm',
    'btn-group-sm': 'sm',
    'btn-lg': 'lg'
};

/** The `text-*` helpers only ever re-toned a btn-link. */
const TONE_BY_TEXT_CLASS: Readonly<Record<string, ButtonTone>> = {
    'text-danger': 'danger',
    'text-success': 'success',
    'text-primary': 'brand',
    'text-secondary': 'neutral',
    'text-muted': 'neutral'
};

const FALLBACK_STYLE: ResolvedButtonStyle = { variant: 'outline', tone: 'neutral' };


/**
 * Resolves a Bootstrap class string to the variant/tone/size it should become.
 *
 * Returns null when the string carries nothing recognisable, so the component keeps its own
 * defaults instead of being forced onto an arbitrary style.
 */
export function resolveBootstrapClass(bootstrapClass: string): ResolvedButtonStyle | null {
    const tokens = (bootstrapClass ?? '').trim().split(/\s+/).filter(Boolean);

    if (!tokens.length) {
        return null;
    }

    let base: ResolvedButtonStyle | null = null;
    let size: ButtonSize | undefined;
    let tone: ButtonTone | undefined;
    let block = false;

    for (const token of tokens) {
        if (!base && STYLE_BY_CLASS[token]) {
            base = STYLE_BY_CLASS[token];
            continue;
        }

        if (!size && SIZE_BY_CLASS[token]) {
            size = SIZE_BY_CLASS[token];
            continue;
        }

        if (!tone && TONE_BY_TEXT_CLASS[token]) {
            tone = TONE_BY_TEXT_CLASS[token];
            continue;
        }

        if (token === 'w-100') {
            block = true;
        }
    }

    if (!base && !size && !tone && !block) {
        return null;
    }

    const resolved = base ?? FALLBACK_STYLE;

    return {
        variant: resolved.variant,
        tone: tone ?? resolved.tone,
        size,
        block
    };
}
