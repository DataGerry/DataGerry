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
import { Injectable } from '@angular/core';

import {
    AutomationDefinition,
    AUTOMATION_DEFINITION_VERSION,
    normalizeAutomationDefinition
} from '../models/automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Result of splitting a stored connection description into its two parts. */
export interface DecodedDescription {
    /** The text the user actually typed. */
    description: string;

    /** The business model, or null for connections built before the wizard (or by the old editor). */
    definition: AutomationDefinition | null;
}

/**
 * Reads and writes the business model that rides along in the OpenCelium connection description.
 *
 * OpenCelium only persists the technical connection JSON, so reopening an automation would
 * otherwise lose every functional choice the user made (trigger, selected fields, mapping). The
 * model is therefore appended to the description as a single HTML comment: invisible in any UI that
 * renders the description, and Base64-encoded so braces, quotes and a literal '-->' inside the
 * model cannot break out of the comment.
 *
 * This service is the only place that knows where the model lives. Should the block outgrow the
 * description field, swapping in a dedicated backend collection means changing this file alone.
 */
@Injectable({ providedIn: 'root' })
export class AutomationDefinitionCodecService {

    /** Marker that identifies our block inside the description. */
    private static readonly MARKER = 'dg-automation';

    /**
     * Size beyond which the encoded block is reported as oversized.
     *
     * OpenCelium does not document a description limit; 16 KiB stays well clear of what any
     * reasonable column would reject while comfortably holding a large mapping.
     */
    public static readonly SIZE_BUDGET_BYTES = 16 * 1024;

    private static readonly BLOCK_RE = new RegExp(
        `\\n?<!--\\s*${AutomationDefinitionCodecService.MARKER}:v(\\d+):([A-Za-z0-9+/=]*)\\s*-->`
    );

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      ENCODING                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Appends the business model to the user's description text.
     *
     * Any block already present is replaced, so encoding is idempotent across repeated saves.
     */
    public encode(description: string, definition: AutomationDefinition): string {
        const humanText = this.stripBlock(description ?? '');
        const payload = this.toBase64(JSON.stringify(definition));
        const block = `<!--${AutomationDefinitionCodecService.MARKER}:v${AUTOMATION_DEFINITION_VERSION}:${payload}-->`;

        return humanText ? `${humanText}\n${block}` : block;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      DECODING                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Splits a stored description into the user's text and the business model.
     *
     * A missing, unreadable or future-version block yields a null definition rather than an error:
     * the wizard then falls back to the read-only technical view instead of failing to open.
     */
    public decode(raw: string | null | undefined): DecodedDescription {
        const text = raw ?? '';
        const match = AutomationDefinitionCodecService.BLOCK_RE.exec(text);

        if (!match) {
            return { description: text, definition: null };
        }

        const description = this.stripBlock(text);
        const version = Number(match[1]);

        if (version > AUTOMATION_DEFINITION_VERSION) {
            return { description, definition: null };
        }

        try {
            const parsed = JSON.parse(this.fromBase64(match[2]));

            return { description, definition: normalizeAutomationDefinition(parsed) };
        } catch {
            // Corrupted block - treat it as absent so the automation stays openable.
            return { description, definition: null };
        }
    }


    /** Whether a description already carries a business model. */
    public hasDefinition(raw: string | null | undefined): boolean {
        return AutomationDefinitionCodecService.BLOCK_RE.test(raw ?? '');
    }


    /**
     * Whether the encoded description exceeds the size budget.
     *
     * Callers warn but still save: the technical connection JSON governs execution, so an oversized
     * block costs only the ability to reopen the automation in the wizard.
     */
    public exceedsSizeBudget(encoded: string): boolean {
        return new TextEncoder().encode(encoded).length > AutomationDefinitionCodecService.SIZE_BUDGET_BYTES;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      INTERNALS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    private stripBlock(text: string): string {
        return text.replace(AutomationDefinitionCodecService.BLOCK_RE, '').trimEnd();
    }


    /** UTF-8 safe Base64 - btoa alone throws on non-Latin-1 characters such as umlauts. */
    private toBase64(text: string): string {
        const bytes = new TextEncoder().encode(text);
        let binary = '';

        bytes.forEach(byte => {
            binary += String.fromCharCode(byte);
        });

        return btoa(binary);
    }


    private fromBase64(payload: string): string {
        const binary = atob(payload);
        const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));

        return new TextDecoder().decode(bytes);
    }
}
