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
    AutomationField,
    AutomationMappingEntry,
    mappedSources
} from '../models/automation-definition.model';
import { TargetField } from '../models/target-catalog.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A suggestion together with why it was made, so the UI can explain itself. */
export interface MappingSuggestion extends AutomationMappingEntry {
    /** Which comparison produced the hit. */
    matchedOn: 'name' | 'label' | 'alias' | 'similarity' | 'none';
}

/**
 * Suggests which source field belongs to which target field.
 *
 * Users should only have to correct what the wizard could not work out by itself, so matching runs
 * from strongest to weakest evidence: technical name, then label, then alias, then normalised
 * similarity. Anything below the threshold is returned unmapped rather than mapped badly - a wrong
 * automatic mapping is more expensive than an empty one.
 */
@Injectable({ providedIn: 'root' })
export class AutomationFieldMappingService {

    /** Minimum similarity for a fuzzy hit. Below this a field is left for the user to map. */
    public static readonly SIMILARITY_THRESHOLD = 0.7;

    private static readonly CONFIDENCE = {
        name: 1,
        label: 0.95,
        alias: 0.9
    };

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     SUGGESTIONS                                                    */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Maps each source field onto at most one target field.
     *
     * Target fields are consumed as they are used, so two source fields never land on the same
     * target. Sources are processed in their given order, which is the order the user picked them.
     */
    public suggest(sourceFields: AutomationField[], targetFields: TargetField[]): MappingSuggestion[] {
        const available = [...(targetFields ?? [])];
        const suggestions: MappingSuggestion[] = [];

        for (const field of sourceFields ?? []) {
            const hit = this.bestMatch(field, available);

            if (!hit) {
                continue;
            }

            available.splice(available.indexOf(hit.target), 1);
            suggestions.push({
                target: hit.target.path,
                sources: [{ field: field.name, origin: 'auto', confidence: hit.confidence }],
                matchedOn: hit.matchedOn
            });
        }

        return suggestions;
    }


    /**
     * Suggests targets for the source fields nobody has decided on yet.
     *
     * Anything already mapped stays untouched, and so does a field the user deliberately left
     * alone - re-suggesting one they just cleared would undo the decision on the next keystroke.
     * Targets already written to are off the table, since a field takes one value.
     */
    public fillGaps(
        existing: AutomationMappingEntry[],
        sourceFields: AutomationField[],
        targetFields: TargetField[],
        unmapped: ReadonlyArray<string> = []
    ): AutomationMappingEntry[] {
        const used = mappedSources(existing);
        const left = new Set(unmapped);
        const takenTargets = new Set(existing.map(entry => entry.target));

        const gaps = (sourceFields ?? []).filter(
            field => !used.has(field.name) && !left.has(field.name)
        );
        const free = (targetFields ?? []).filter(field => !takenTargets.has(field.path));

        if (gaps.length === 0) {
            return existing;
        }

        const added = this.suggest(gaps, free)
            .map(({ target, sources }) => ({ target, sources }));

        return added.length > 0 ? [...existing, ...added] : existing;
    }


    /** Drops the sources that are no longer offered, and the entries left without any. */
    public prune(
        existing: AutomationMappingEntry[],
        sourceFields: AutomationField[],
        targetFields: TargetField[]
    ): AutomationMappingEntry[] {
        const offered = new Set((sourceFields ?? []).map(field => field.name));
        const targets = new Set((targetFields ?? []).map(field => field.path));

        const kept = existing
            .filter(entry => targets.has(entry.target))
            .map(entry => ({ ...entry, sources: entry.sources.filter(source => offered.has(source.field)) }))
            .filter(entry => entry.sources.length > 0);

        const unchanged = kept.length === existing.length
            && kept.every((entry, index) => entry.sources.length === existing[index].sources.length);

        return unchanged ? existing : kept;
    }


    /** Source fields that are offered but do not feed anything yet. */
    public unassigned(mapping: AutomationMappingEntry[], sourceFields: AutomationField[]): string[] {
        const used = mappedSources(mapping ?? []);

        return (sourceFields ?? []).map(field => field.name).filter(name => !used.has(name));
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       MATCHING                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    private bestMatch(
        field: AutomationField,
        targets: TargetField[]
    ): { target: TargetField; confidence: number; matchedOn: MappingSuggestion['matchedOn'] } | null {
        if (targets.length === 0) {
            return null;
        }

        const name = this.normalize(field.name);
        const label = this.normalize(field.label);

        const byName = targets.find(target => this.normalize(target.name) === name
            || this.normalize(target.path) === name);

        if (byName) {
            return { target: byName, confidence: AutomationFieldMappingService.CONFIDENCE.name, matchedOn: 'name' };
        }

        if (label) {
            const byLabel = targets.find(target => this.normalize(target.name) === label);

            if (byLabel) {
                return {
                    target: byLabel,
                    confidence: AutomationFieldMappingService.CONFIDENCE.label,
                    matchedOn: 'label'
                };
            }
        }

        const byAlias = this.matchByAlias(name, label, targets);

        if (byAlias) {
            return { target: byAlias, confidence: AutomationFieldMappingService.CONFIDENCE.alias, matchedOn: 'alias' };
        }

        return this.matchBySimilarity(name, label, targets);
    }


    /**
     * Matches through the well-known synonyms of CMDB attributes.
     *
     * Systems name the same thing differently - a DataGerry 'hostname' is i-doit's 'title' - and no
     * amount of string similarity bridges that, so the common pairs are listed explicitly.
     */
    private matchByAlias(name: string, label: string, targets: TargetField[]): TargetField | null {
        const aliases = ALIAS_GROUPS.find(group => group.includes(name) || (label && group.includes(label)));

        if (!aliases) {
            return null;
        }

        return targets.find(target => aliases.includes(this.normalize(target.name))) ?? null;
    }


    private matchBySimilarity(
        name: string,
        label: string,
        targets: TargetField[]
    ): { target: TargetField; confidence: number; matchedOn: MappingSuggestion['matchedOn'] } | null {
        let best: { target: TargetField; score: number } | null = null;

        for (const target of targets) {
            const candidate = this.normalize(target.name);
            const score = Math.max(
                this.similarity(name, candidate),
                label ? this.similarity(label, candidate) : 0
            );

            if (!best || score > best.score) {
                best = { target, score };
            }
        }

        if (!best || best.score < AutomationFieldMappingService.SIMILARITY_THRESHOLD) {
            return null;
        }

        return { target: best.target, confidence: Math.round(best.score * 100) / 100, matchedOn: 'similarity' };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      INTERNALS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /** Lowercases and drops separators so 'serial_number', 'serialNumber' and 'Serial Number' agree. */
    private normalize(value: string | null | undefined): string {
        return (value ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');
    }


    /** Levenshtein distance turned into a 0..1 score. */
    private similarity(left: string, right: string): number {
        if (!left || !right) {
            return 0;
        }

        if (left === right) {
            return 1;
        }

        const distance = this.levenshtein(left, right);

        return 1 - distance / Math.max(left.length, right.length);
    }


    /** Two-row Levenshtein - the full matrix is never needed for field names. */
    private levenshtein(left: string, right: string): number {
        let previous = Array.from({ length: right.length + 1 }, (_, index) => index);

        for (let i = 1; i <= left.length; i++) {
            const current = [i];

            for (let j = 1; j <= right.length; j++) {
                const substitution = previous[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1);
                current[j] = Math.min(current[j - 1] + 1, previous[j] + 1, substitution);
            }

            previous = current;
        }

        return previous[right.length];
    }
}

/**
 * Synonym groups for attributes that recur across CMDBs and ticket systems.
 *
 * Kept flat and normalised (lowercase, no separators) so a lookup is a plain includes().
 */
const ALIAS_GROUPS: ReadonlyArray<ReadonlyArray<string>> = [
    ['title', 'name', 'label', 'hostname', 'displayname', 'summary'],
    ['description', 'comment', 'note', 'notes', 'remark'],
    ['serialnumber', 'serial', 'serialno', 'sysid'],
    ['inventorynumber', 'inventarnummer', 'assettag', 'inventoryno'],
    ['ipaddress', 'ip', 'ipv4', 'address'],
    ['manufacturer', 'vendor', 'hersteller', 'make'],
    ['model', 'modell', 'producttype'],
    ['location', 'standort', 'site', 'room'],
    ['status', 'state', 'cmdbstatus', 'condition'],
    ['type', 'typeid', 'objecttype', 'category'],
    ['owner', 'assignee', 'responsible', 'contact'],
    ['createdat', 'created', 'creationtime', 'createdon'],
    ['updatedat', 'updated', 'lastedittime', 'modifiedon']
];
