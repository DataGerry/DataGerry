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

import { OutlineNavItem } from '../models/docapi-outline.model';
import {
    buildOutlineTree,
    OUTLINE_HEADING_SELECTOR,
    OUTLINE_ID_ATTRIBUTE,
    OUTLINE_MAX_HEADING_LEVEL
} from './docapi-outline-tree.util';
import { parseEditorBodyWithOutlineIds, resolveSectionRangeInBodyByHeadingId } from './docapi-outline-section-range.util';

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));

const deepCloneTree = (tree: OutlineNavItem[]): OutlineNavItem[] =>
    tree.map((node) => ({
        ...node,
        children: deepCloneTree(node.children)
    }));

const findNodeById = (tree: OutlineNavItem[], targetId: string): OutlineNavItem | null => {
    for (const node of tree) {
        if (node.id === targetId) {
            return node;
        }

        const nested = findNodeById(node.children, targetId);
        if (nested) {
            return nested;
        }
    }

    return null;
};

const findAndDetachNode = (
    tree: OutlineNavItem[],
    targetId: string
): { treeWithoutNode: OutlineNavItem[]; detachedNode: OutlineNavItem | null } => {
    const nextTree: OutlineNavItem[] = [];

    for (const node of tree) {
        if (node.id === targetId) {
            return {
                treeWithoutNode: [...nextTree, ...tree.slice(nextTree.length + 1)],
                detachedNode: node
            };
        }

        const nested = findAndDetachNode(node.children, targetId);
        if (nested.detachedNode) {
            nextTree.push({
                ...node,
                children: nested.treeWithoutNode
            });

            return {
                treeWithoutNode: [...nextTree, ...tree.slice(nextTree.length)],
                detachedNode: nested.detachedNode
            };
        }

        nextTree.push(node);
    }

    return { treeWithoutNode: tree, detachedNode: null };
};

const subtreeContainsId = (node: OutlineNavItem, targetId: string): boolean =>
    node.id === targetId || node.children.some((child) => subtreeContainsId(child, targetId));

const insertNodeIntoParent = (
    tree: OutlineNavItem[],
    parentId: string | null,
    index: number,
    nodeToInsert: OutlineNavItem
): { nextTree: OutlineNavItem[]; inserted: boolean } => {
    if (parentId === null) {
        const boundedIndex = clamp(index, 0, tree.length);
        const next = [...tree];
        next.splice(boundedIndex, 0, nodeToInsert);
        return { nextTree: next, inserted: true };
    }

    let inserted = false;

    const nextTree = tree.map((node) => {
        if (node.id === parentId) {
            const boundedIndex = clamp(index, 0, node.children.length);
            const nextChildren = [...node.children];
            nextChildren.splice(boundedIndex, 0, nodeToInsert);
            inserted = true;
            return {
                ...node,
                children: nextChildren
            };
        }

        const nested = insertNodeIntoParent(node.children, parentId, index, nodeToInsert);
        if (nested.inserted) {
            inserted = true;
        }

        return {
            ...node,
            children: nested.nextTree
        };
    });

    return { nextTree, inserted };
};

export const moveItemInTree = (
    tree: OutlineNavItem[],
    movedId: string,
    destinationParentId: string | null,
    destinationIndex: number
): OutlineNavItem[] => {
    // Detach and reinsert in a cloned tree; reject drops into own descendants.
    if (!movedId || tree.length === 0) {
        return tree;
    }

    const nextTree = deepCloneTree(tree);

    if (destinationParentId && !findNodeById(nextTree, destinationParentId)) {
        return tree;
    }

    const detachResult = findAndDetachNode(nextTree, movedId);
    if (!detachResult.detachedNode) {
        return tree;
    }

    if (destinationParentId && subtreeContainsId(detachResult.detachedNode, destinationParentId)) {
        return tree;
    }

    const insertResult = insertNodeIntoParent(
        detachResult.treeWithoutNode,
        destinationParentId,
        destinationIndex,
        detachResult.detachedNode
    );

    if (!insertResult.inserted) {
        return tree;
    }

    return insertResult.nextTree;
};

const setHeadingTagByLevel = (heading: HTMLElement, level: number): HTMLElement => {
    const normalizedLevel = clamp(level, 1, OUTLINE_MAX_HEADING_LEVEL);
    const targetTagName = `h${normalizedLevel}`;

    if (heading.tagName.toLowerCase() === targetTagName) {
        return heading;
    }

    const replacement = heading.ownerDocument.createElement(targetTagName);
    Array.from(heading.attributes).forEach((attribute) => replacement.setAttribute(attribute.name, attribute.value));
    replacement.innerHTML = heading.innerHTML;
    heading.replaceWith(replacement);
    return replacement;
};

const resolveHeadingElementById = (body: HTMLElement, headingId: string): HTMLElement | null => {
    const headings = Array.from(body.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
    return headings.find((heading) => heading.getAttribute(OUTLINE_ID_ATTRIBUTE) === headingId) ?? null;
};

interface SectionSnapshot {
    headingElement: HTMLElement;
    directBodyNodes: Node[];
    rangeIndexes: number[];
}

interface OrphanContentBuckets {
    prefixNodes: Node[];
    suffixNodes: Node[];
    afterSectionNodes: Map<string, Node[]>;
}

const buildSectionSnapshots = (sourceTree: OutlineNavItem[], sourceBody: HTMLElement): Map<string, SectionSnapshot> => {
    const snapshots = new Map<string, SectionSnapshot>();

    const visit = (nodes: OutlineNavItem[]): void => {
        nodes.forEach((node) => {
            // Capture section heading + direct non-heading body, excluding child section ranges.
            const sectionRange = resolveSectionRangeInBodyByHeadingId(sourceBody, node.id);
            const headingElement = resolveHeadingElementById(sourceBody, node.id);

            if (sectionRange && headingElement) {
                const childIndexSet = new Set<number>();

                node.children.forEach((childNode) => {
                    const childRange = resolveSectionRangeInBodyByHeadingId(sourceBody, childNode.id);
                    if (!childRange) {
                        return;
                    }

                    for (let index = childRange.startIndex; index <= childRange.endIndex; index += 1) {
                        childIndexSet.add(index);
                    }
                });

                const directBodyNodes: Node[] = [];
                for (let index = sectionRange.startIndex + 1; index <= sectionRange.endIndex; index += 1) {
                    if (childIndexSet.has(index)) {
                        continue;
                    }

                    const nodeAtIndex = sectionRange.bodyNodes[index];
                    if (nodeAtIndex) {
                        directBodyNodes.push(nodeAtIndex.cloneNode(true));
                    }
                }

                const rangeIndexes: number[] = [];
                for (let index = sectionRange.startIndex; index <= sectionRange.endIndex; index += 1) {
                    rangeIndexes.push(index);
                }

                snapshots.set(node.id, {
                    headingElement: headingElement.cloneNode(true) as HTMLElement,
                    directBodyNodes,
                    rangeIndexes
                });
            }

            visit(node.children);
        });
    };

    visit(sourceTree);
    return snapshots;
};

const appendSerializedSubtree = (
    ownerDocument: Document,
    parent: HTMLElement,
    nodes: OutlineNavItem[],
    snapshots: Map<string, SectionSnapshot>,
    depth: number,
    onNodeSerialized?: (nodeId: string) => void
): void => {
    nodes.forEach((node) => {
        const snapshot = snapshots.get(node.id);
        const headingLevel = depth + 1;

        const headingElement = snapshot
            ? setHeadingTagByLevel(snapshot.headingElement.cloneNode(true) as HTMLElement, headingLevel)
            : ownerDocument.createElement(`h${clamp(headingLevel, 1, OUTLINE_MAX_HEADING_LEVEL)}`);

        if (!snapshot) {
            headingElement.setAttribute(OUTLINE_ID_ATTRIBUTE, node.id);
            headingElement.textContent = node.text;
        }

        parent.appendChild(headingElement);

        if (snapshot) {
            snapshot.directBodyNodes.forEach((bodyNode) => {
                parent.appendChild(bodyNode.cloneNode(true));
            });
        }

        appendSerializedSubtree(ownerDocument, parent, node.children, snapshots, depth + 1, onNodeSerialized);
        onNodeSerialized?.(node.id);
    });
};

const flattenTreeIds = (tree: OutlineNavItem[]): string[] => {
    const ids: string[] = [];

    const visit = (nodes: OutlineNavItem[]): void => {
        nodes.forEach((node) => {
            ids.push(node.id);
            visit(node.children);
        });
    };

    visit(tree);
    return ids;
};

const getRangeStart = (snapshot: SectionSnapshot): number => Math.min(...snapshot.rangeIndexes);

const getRangeEnd = (snapshot: SectionSnapshot): number => Math.max(...snapshot.rangeIndexes);

const buildOrphanContentBuckets = (
    sourceBodyNodes: Node[],
    originalSectionOrder: string[],
    snapshots: Map<string, SectionSnapshot>
): OrphanContentBuckets => {
    // Keep orphan non-heading nodes aligned with their original section boundaries.
    const usedIndexes = new Set<number>();
    snapshots.forEach((snapshot) => {
        snapshot.rangeIndexes.forEach((index) => usedIndexes.add(index));
    });

    const prefixNodes: Node[] = [];
    const suffixNodes: Node[] = [];
    const afterSectionNodes = new Map<string, Node[]>();

    if (originalSectionOrder.length === 0) {
        sourceBodyNodes.forEach((node) => prefixNodes.push(node.cloneNode(true)));
        return { prefixNodes, suffixNodes, afterSectionNodes };
    }

    const firstSnapshot = snapshots.get(originalSectionOrder[0]);
    const firstSectionStart = firstSnapshot ? getRangeStart(firstSnapshot) : sourceBodyNodes.length;

    for (let index = 0; index < firstSectionStart; index += 1) {
        if (!usedIndexes.has(index)) {
            prefixNodes.push(sourceBodyNodes[index].cloneNode(true));
        }
    }

    for (let orderIndex = 0; orderIndex < originalSectionOrder.length; orderIndex += 1) {
        const sectionId = originalSectionOrder[orderIndex];
        const sectionSnapshot = snapshots.get(sectionId);
        if (!sectionSnapshot) {
            continue;
        }

        const currentSectionEnd = getRangeEnd(sectionSnapshot);
        const nextSectionSnapshot = orderIndex + 1 < originalSectionOrder.length
            ? snapshots.get(originalSectionOrder[orderIndex + 1])
            : null;

        const boundaryEnd = nextSectionSnapshot ? getRangeStart(nextSectionSnapshot) : sourceBodyNodes.length;
        const bucketNodes: Node[] = [];

        for (let index = currentSectionEnd + 1; index < boundaryEnd; index += 1) {
            if (usedIndexes.has(index)) {
                continue;
            }

            bucketNodes.push(sourceBodyNodes[index].cloneNode(true));
        }

        if (nextSectionSnapshot) {
            if (bucketNodes.length > 0) {
                afterSectionNodes.set(sectionId, bucketNodes);
            }
        } else {
            suffixNodes.push(...bucketNodes);
        }
    }

    return { prefixNodes, suffixNodes, afterSectionNodes };
};

export const serializeTreeToHtml = (tree: OutlineNavItem[], originalHtml: string): string => {
    // Rebuild HTML from tree order while preserving non-heading content placement.
    const sourceBody = parseEditorBodyWithOutlineIds(originalHtml ?? '');
    const sourceOutlineTree = buildOutlineTree(sourceBody).tree;
    const snapshots = buildSectionSnapshots(sourceOutlineTree, sourceBody);

    const outputDocument = new DOMParser().parseFromString('', 'text/html');
    const outputBody = outputDocument.body;

    const sourceBodyNodes = Array.from(sourceBody.childNodes);
    const originalSectionOrder = flattenTreeIds(sourceOutlineTree);
    const orphanBuckets = buildOrphanContentBuckets(sourceBodyNodes, originalSectionOrder, snapshots);
    const appendedBuckets = new Set<string>();

    orphanBuckets.prefixNodes.forEach((node) => outputBody.appendChild(node));
    appendSerializedSubtree(outputDocument, outputBody, tree, snapshots, 0, (nodeId: string) => {
        const bucket = orphanBuckets.afterSectionNodes.get(nodeId);
        if (!bucket || appendedBuckets.has(nodeId)) {
            return;
        }

        bucket.forEach((node) => outputBody.appendChild(node.cloneNode(true)));
        appendedBuckets.add(nodeId);
    });
    orphanBuckets.suffixNodes.forEach((node) => outputBody.appendChild(node));

    return outputBody.innerHTML;
};
