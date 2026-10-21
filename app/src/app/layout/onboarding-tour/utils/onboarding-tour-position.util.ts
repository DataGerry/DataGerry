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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { TourBounds, TourCardPosition, TourPlacement, TourRect, TourSize } from '../models/onboarding-tour.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const SPOTLIGHT_PADDING = 4;
const CARD_GAP = 16;
const VIEWPORT_MARGIN = 16;
const ARROW_INSET = 24;

/** Room for the header, the footer and a few lines of scrolling body. */
const MIN_SQUEEZED_HEIGHT = 288;

/** Spacing used before shortening, so a card a few pixels too tall keeps its full height; too tight for the arrow. */
const TIGHT_GAP = 8;
const TIGHT_MARGIN = 8;

const PLACEMENT_ORDER: Record<TourPlacement, TourPlacement[]> = {
    bottom: ['bottom', 'top', 'right', 'left'],
    top: ['top', 'bottom', 'right', 'left'],
    right: ['right', 'left', 'bottom', 'top'],
    left: ['left', 'right', 'bottom', 'top']
};

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

/** Client size excludes scrollbars, which the fixed overlay must not cover. */
export function getViewportSize(root: Document): TourSize {
    return { width: root.documentElement.clientWidth, height: root.documentElement.clientHeight };
}


/** Returns the element only when it is rendered and at least partly inside the viewport. */
export function findVisibleTarget(root: Document, selector: string, viewport: TourSize): HTMLElement | null {
    const element = root.querySelector<HTMLElement>(selector);

    if (!element) {
        return null;
    }

    const rect = element.getBoundingClientRect();
    const isRendered = rect.width > 0 && rect.height > 0;
    const isInViewport = rect.right > 0 && rect.bottom > 0 && rect.left < viewport.width && rect.top < viewport.height;

    return isRendered && isInViewport ? element : null;
}


/** Bounds of the target together with any of its children that overflow it. */
export function measureTarget(target: HTMLElement, include?: string): TourBounds {
    const rects = [target, ...(include ? Array.from(target.querySelectorAll<HTMLElement>(include)) : [])]
        .map(element => element.getBoundingClientRect());

    return {
        top: Math.min(...rects.map(rect => rect.top)),
        left: Math.min(...rects.map(rect => rect.left)),
        right: Math.max(...rects.map(rect => rect.right)),
        bottom: Math.max(...rects.map(rect => rect.bottom))
    };
}


export function resolveSpotlight(rect: TourBounds, viewport: TourSize): TourRect {
    const top = Math.max(rect.top - SPOTLIGHT_PADDING, VIEWPORT_MARGIN / 2);
    const left = Math.max(rect.left - SPOTLIGHT_PADDING, VIEWPORT_MARGIN / 2);
    const bottom = Math.min(rect.bottom + SPOTLIGHT_PADDING, viewport.height - VIEWPORT_MARGIN / 2);
    const right = Math.min(rect.right + SPOTLIGHT_PADDING, viewport.width - VIEWPORT_MARGIN / 2);

    return { top, left, width: right - left, height: bottom - top };
}


export function resolveCenteredCard(card: TourSize, viewport: TourSize): TourCardPosition {
    return {
        placement: 'center',
        top: Math.max((viewport.height - card.height) / 2, VIEWPORT_MARGIN),
        left: Math.max((viewport.width - card.width) / 2, VIEWPORT_MARGIN),
        arrowOffset: 0,
        maxHeight: null
    };
}


/**
 * Tries the preferred side first, then the opposite one. When no side fits the full card, it moves closer to the
 * roomier vertical side and is shortened if needed; it floats over the target only when even that is too tight.
 */
export function resolveCardPosition(
    target: TourRect,
    card: TourSize,
    viewport: TourSize,
    preferred: TourPlacement
): TourCardPosition {
    const placement = PLACEMENT_ORDER[preferred].find(side => hasRoom(side, target, card, viewport));

    if (placement) {
        return placeBeside(placement, target, card, viewport, CARD_GAP, null);
    }

    const below = viewport.height - (target.top + target.height);
    const side: TourPlacement = below >= target.top ? 'bottom' : 'top';
    const room = Math.max(below, target.top);

    if (card.height <= room - TIGHT_GAP - TIGHT_MARGIN) {
        return { ...placeBeside(side, target, card, viewport, TIGHT_GAP, null), placement: 'floating', arrowOffset: 0 };
    }

    const space = room - CARD_GAP - VIEWPORT_MARGIN;

    if (space >= MIN_SQUEEZED_HEIGHT) {
        return placeBeside(side, target, { width: card.width, height: space }, viewport, CARD_GAP, space);
    }

    return {
        placement: 'floating',
        top: Math.max(viewport.height - card.height - VIEWPORT_MARGIN, VIEWPORT_MARGIN),
        left: clamp(
            target.left + target.width / 2 - card.width / 2,
            VIEWPORT_MARGIN,
            viewport.width - card.width - VIEWPORT_MARGIN
        ),
        arrowOffset: 0,
        maxHeight: null
    };
}


/** A squeezed card scrolls its body, so the hidden overflow is added back to get its full height. */
export function measureCardHeight(card: HTMLElement): number {
    const body = card.querySelector<HTMLElement>('.dg-modal__body');

    return card.offsetHeight + (body ? body.scrollHeight - body.clientHeight : 0);
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function placeBeside(
    placement: TourPlacement,
    target: TourRect,
    card: TourSize,
    viewport: TourSize,
    gap: number,
    maxHeight: number | null
): TourCardPosition {
    const isVertical = placement === 'top' || placement === 'bottom';
    const targetCenterX = target.left + target.width / 2;
    const targetCenterY = target.top + target.height / 2;

    const left = isVertical
        ? clamp(targetCenterX - card.width / 2, VIEWPORT_MARGIN, viewport.width - card.width - VIEWPORT_MARGIN)
        : placement === 'right'
            ? target.left + target.width + gap
            : target.left - gap - card.width;

    const top = isVertical
        ? placement === 'bottom'
            ? target.top + target.height + gap
            : target.top - gap - card.height
        : clamp(targetCenterY - card.height / 2, VIEWPORT_MARGIN, viewport.height - card.height - VIEWPORT_MARGIN);

    const arrowOffset = isVertical
        ? clamp(targetCenterX - left, ARROW_INSET, card.width - ARROW_INSET)
        : clamp(targetCenterY - top, ARROW_INSET, card.height - ARROW_INSET);

    return { placement, top, left, arrowOffset, maxHeight };
}


function hasRoom(side: TourPlacement, target: TourRect, card: TourSize, viewport: TourSize): boolean {
    switch (side) {
        case 'bottom':
            return viewport.height - (target.top + target.height) - CARD_GAP >= card.height + VIEWPORT_MARGIN;
        case 'top':
            return target.top - CARD_GAP >= card.height + VIEWPORT_MARGIN;
        case 'right':
            return viewport.width - (target.left + target.width) - CARD_GAP >= card.width + VIEWPORT_MARGIN;
        case 'left':
            return target.left - CARD_GAP >= card.width + VIEWPORT_MARGIN;
    }
}


function clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), Math.max(min, max));
}
