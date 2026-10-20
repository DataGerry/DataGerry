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
import { LocationTreeSelectNode } from '../location-tree-select/location-tree-select.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Result of a drop-eligibility check: whether the move is allowed and, if not, a user-facing reason. */
export interface DropCheck {
    ok: boolean;
    reason: string | null;
}

/** User-facing reasons a drop is rejected, shown in the drag hint. */
export const DROP_REASON = {
    self: "A location can't be its own parent",
    descendant: "Can't move a location into one of its own sub-locations",
    notSelectable: "This location type can't contain other locations",
    alreadyHere: 'Already in this location',
    alreadyTop: 'Already at the top level'
} as const;

/**
 * Decides whether the dragged locations may drop onto a target and, when they may not, why. Rejected
 * when the target can't hold children, is one of the dragged nodes, is a descendant of a dragged node,
 * or already holds every dragged node (a no-op). The descendant check is best-effort over the loaded
 * portion of the tree.
 *
 * @param targetId    public_id of the drop target (rootId = top level)
 * @param draggedIds  public_ids being moved
 * @param nodesById   the loaded nodes, keyed by public_id
 * @param rootId      public_id of the synthetic root / top level
 */
export function evaluateDrop(
    targetId: number,
    draggedIds: Set<number>,
    nodesById: ReadonlyMap<number, LocationTreeSelectNode>,
    rootId: number
): DropCheck {
    if (draggedIds.size === 0) {
        return { ok: false, reason: null };
    }

    if (targetId === rootId) {
        return draggedIds.has(rootId) ? { ok: false, reason: null } : noOpOr(targetId, draggedIds, nodesById, rootId);
    }

    const target = nodesById.get(targetId);
    if (!target) {
        return { ok: false, reason: null };
    }

    if (!target.selectable) {
        return { ok: false, reason: DROP_REASON.notSelectable };
    }

    // target itself, or any of its ancestors, being dragged means it sits inside a moved subtree
    for (let cursor: LocationTreeSelectNode | undefined = target; cursor; cursor = nodesById.get(cursor.parent)) {
        if (draggedIds.has(cursor.public_id)) {
            return { ok: false, reason: cursor.public_id === targetId ? DROP_REASON.self : DROP_REASON.descendant };
        }
    }

    return noOpOr(targetId, draggedIds, nodesById, rootId);
}

/** Rejects a pure no-op (every dragged node already sits under the target), otherwise allows the drop. */
function noOpOr(
    targetId: number,
    draggedIds: Set<number>,
    nodesById: ReadonlyMap<number, LocationTreeSelectNode>,
    rootId: number
): DropCheck {
    for (const id of draggedIds) {
        if (nodesById.get(id)?.parent !== targetId) {
            return { ok: true, reason: null };
        }
    }

    return { ok: false, reason: targetId === rootId ? DROP_REASON.alreadyTop : DROP_REASON.alreadyHere };
}
