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
import { ButtonTone } from 'src/app/core/components/base/button/app-button.types';
/* ------------------------------------------------------------------------------------------------------------------ */

export const PERSON_SYNC_EDIT_RIGHT = 'base.user-management.sync.edit';

export type SystemRefKind = 'user' | 'user_group';

/** Links an object to the user-management record the sync mirrors into it. */
export interface SystemRef {
    kind: SystemRefKind;
    id: number;
}

export interface PersonTypeOverride {
    user_id: number;
    type_id: number;
}

export interface UserSyncSettings {
    active: boolean;
    default_type_id: number | null;
    type_overrides: PersonTypeOverride[];
}

export type OnBlocked = 'cancel' | 'copy';

export interface UserSyncRequest extends UserSyncSettings {
    on_blocked?: OnBlocked;
}

/** The synced persons a pass took out of one mapped person group. */
export interface LeftMembers {
    person_group_id: number;
    person_ids: number[];
}

export interface SyncPassResult<T> {
    created: number;
    edited: number;
    left: LeftMembers[];
    result: T;
}

export interface UserSyncPassResult extends SyncPassResult<UserSyncSettings> {
    moved?: number;
    copied?: number;
}

export interface PersonRelocation {
    user_id: number;
    person_id: number;
    from_type_id: number;
    to_type_id: number;
    blockers: string[];
}

export interface UserSyncCheck {
    relocations: PersonRelocation[];
    blocked: number;
}

export interface GroupMapping {
    user_group_id: number;
    person_group_id: number;
}

export interface GroupSyncSettings {
    active: boolean;
    mappings: GroupMapping[];
}

/** Exactly one key: an existing person group, or the Type a new one is created in. */
export type GroupMappingRequest = { person_group_id: number } | { type_id: number };

export interface GroupMappingResult {
    left: LeftMembers[];
    result: GroupMapping;
}

export interface UserPerson {
    user_id: number;
    person_id: number | null;
    type_id: number | null;
}


/** What a pass wrote; a settings save sends every count, a resync or a mapping only some. */
export interface SyncPassCounts {
    created?: number;
    edited?: number;
    moved?: number;
    copied?: number;
    left?: LeftMembers[];
}

export interface SyncPassSummary {
    counts: { label: string; value: number }[];
    left: LeftMembers[];
}

export interface BlockedPersonRow extends PersonRelocation {
    user_label: string;
}

export interface SyncConfirmation {
    title: string;
    message: string;
    confirmLabel: string;
    confirmTone?: ButtonTone;
    warningMessage?: string;
}

/** What the record a synced object mirrors is called, and where it opens; no link without the right. */
export interface SyncSourceLink {
    text: string;
    link: string[] | null;
}

export type GroupMapTarget = 'existing' | 'new';

export interface SyncSelectOption {
    public_id: number;
    label: string;
}
