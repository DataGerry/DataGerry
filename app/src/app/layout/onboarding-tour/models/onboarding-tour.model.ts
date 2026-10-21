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
/* ------------------------------------------------------------------------------------------------------------------ */

/* --------------------------------------------------- TYPES --------------------------------------------------- */

export type TourPlacement = 'top' | 'bottom' | 'left' | 'right';

/** `floating` has no arrow: the card sits over the target, or too close to it for the arrow. */
export type TourCardPlacement = TourPlacement | 'center' | 'floating';

export type TourStepKind = 'intro' | 'spotlight' | 'outro';

/** A small drawing rendered inside the card. */
export type TourIllustration = 'framework-menu' | 'type-content' | 'object-form';

export type TourDirection = 'forward' | 'backward';

export type TourChapterState = 'done' | 'active' | 'upcoming';

/* ------------------------------------------------- INTERFACES ------------------------------------------------ */

/** Follow-up link on the outro step; `href` opens an external page. */
export interface TourAction {
    icon: string;
    title: string;
    text: string;
    route?: string;
    href?: string;

    /** A route link shows only for users with this right. */
    right?: string;
}

/** A tile in a step's feature grid. */
export interface TourFeature {
    icon: string;
    title: string;
    text: string;

    /** The tile shows only for users with all of these rights. */
    right?: string | string[];
}


/** One line of a numbered list inside a step. */
export interface TourPoint {
    title: string;
    text: string;
}

/** A group of spotlight steps; `title` matches the `chapter` of its steps. */
export interface TourChapter {
    title: string;
    text: string;
}

/** A chapter that has at least one step in the running tour. */
export interface TourChapterRange extends TourChapter {
    startIndex: number;
    stepCount: number;
}

export interface TourChapterProgress extends TourChapterRange {
    state: TourChapterState;

    /** Share of the chapter's steps already reached, in percent. */
    fill: number;
}

export interface TourStep {
    id: string;
    kind: TourStepKind;
    chapter: string;
    icon: string;
    title: string;
    text: string;
    tip?: string;

    /** CSS selector of the element to spotlight; intro and outro steps have none. */
    target?: string;

    /** Children of the target drawn outside its box, merged into the spotlight. */
    include?: string;

    /** Route the step is shown on; shell targets (navbar, sidebar) need none. */
    route?: string;

    /** The step is skipped for users without this right. */
    right?: string;
    placement?: TourPlacement;
    points?: TourPoint[];
    features?: TourFeature[];
    illustration?: TourIllustration;
    actions?: TourAction[];
}

export interface TourRect {
    top: number;
    left: number;
    width: number;
    height: number;
}

export type TourBounds = Pick<DOMRect, 'top' | 'left' | 'right' | 'bottom'>;

export interface TourSize {
    width: number;
    height: number;
}

export interface TourCardPosition {
    placement: TourCardPlacement;
    top: number;
    left: number;

    /** Arrow position along the card edge that faces the target. */
    arrowOffset: number;

    /** Set when the card is shortened to fit beside its target; the body scrolls instead. */
    maxHeight: number | null;
}

export interface TourLayout {
    /** Step the layout was measured for; the previous one stays on screen while a routed target loads. */
    stepId: string;

    /** Collapses to the viewport center when the step has no target, so the backdrop morphs between steps. */
    spotlight: TourRect;
    hasTarget: boolean;
    card: TourCardPosition;
}
