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
import { EDGE_STYLES } from '../../graph-editor/constants/graph.constants';
import { CablingDisplayOptions } from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Card geometry in canvas pixels. The node template binds these, so layout and render cannot drift. */
export const CABLING_GEOMETRY = {
    headerHeight: 58,
    bodyPadding: 6,
    footerHeight: 30,
    emptyHeight: 30,
    rowHeight: {
        standard: { compact: 30, detail: 46 },
        panel: { compact: 44, detail: 60 }
    },
    width: {
        standard: { compact: 260, detail: 320 },
        panel: { compact: 320, detail: 400 }
    },
    columnGap: 150,
    subColumnGap: 60,
    nodeGap: 36,
    curveMin: 40,
    endDotRadius: 4
} as const;

/** Columns counted from the focal object; every patch panel shares the one on its left. */
export const CABLING_COLUMNS = { first: -2, panels: -1, focal: 0, neighbours: 1, last: 2 } as const;

/** Past this many cards the neighbours column splits into two sub-columns. */
export const CABLING_WRAP_AFTER = 6;

/** How far cables bow out beside a card; brackets and hooks on one side nest a step apart. */
export const CABLING_ROUTING = { bracketReach: 24, bracketStep: 14, hookReach: 24, hookStep: 10 } as const;

/** Rows a card shows before the rest fold under "more ports". */
export const CABLING_ROW_LIMIT = { compact: 3, detail: 8 } as const;

export const CABLING_ZOOM = { min: 0.25, max: 2, step: 1.2 } as const;

/** Room kept free around a fitted drawing. */
export const CABLING_FIT_INSETS = { top: 48, right: 48, bottom: 48, left: 48 } as const;

/** Arrow-key pan distance in screen pixels. */
export const CABLING_PAN_STEP = 48;

/** Cable tooltip in screen pixels; `maxHeight` is the tallest it renders, used to decide when it flips below. */
export const CABLING_TOOLTIP = { width: 232, maxHeight: 180, gap: 20, margin: 8, arrowInset: 16 } as const;

/** A cable without a paintable colour keeps the CI Explorer's cable colour. */
export const DEFAULT_CABLE_STROKE = EDGE_STYLES.cable.stroke;

/** Drawn under every cable so a pale one (white, yellow) still clears 3:1 against the canvas. */
export const CABLE_CASING_STROKE = '#64748b';

export const NEUTRAL_ACCENT = '#64748b';

export const DEFAULT_NODE_ICON = 'fas fa-cube';

export const DEFAULT_DISPLAY_OPTIONS: CablingDisplayOptions = {
    detail: false,
    showCableInfo: true,
    showPorts: true,
    onlyConnected: true
};

export const RESTRICTED_OBJECT_LABEL = 'Restricted object';
