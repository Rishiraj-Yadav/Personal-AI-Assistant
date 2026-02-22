import { Page } from "playwright-core";
import crypto from "crypto";

export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface InteractiveElement {
    id: number;
    backendNodeId: number;
    type: string;
    name: string;
    value: string;
    rect: BoundingBox;
}

export interface VisionCache {
    hash: string;
    url: string;
    elements: InteractiveElement[];
    timestamp: number;
}

let activeCache: VisionCache | null = null;
const CACHE_TTL_MS = 10000; // 10s

/**
 * Creates a unique hash of the dynamic DOM to detect React SPA re-renders
 * even when the URL hasn't changed.
 */
async function generateDomHash(page: Page): Promise<string> {
    // Edge case fix from user: slice to 100 to avoid minor length collisions
    const content = await page.evaluate(() => document.body.textContent?.slice(0, 100) || "");
    const url = page.url();
    return crypto.createHash("md5").update(content + url).digest("hex");
}

export async function invalidateCache() {
    activeCache = null;
}

/**
 * Extracts all interactive elements (buttons, inputs, links) from the current
 * viewport using the Chrome DevTools Protocol (CDP) DOMSnapshot.
 */
export async function extractInteractiveElements(page: Page): Promise<InteractiveElement[]> {
    const currentUrl = page.url();
    const currentHash = await generateDomHash(page);
    const now = Date.now();

    // Return cached result if valid
    if (
        activeCache &&
        activeCache.url === currentUrl &&
        activeCache.hash === currentHash &&
        (now - activeCache.timestamp) < CACHE_TTL_MS
    ) {
        return activeCache.elements;
    }

    const cdp = await page.context().newCDPSession(page);
    try {
        const { documents, strings } = await cdp.send("DOMSnapshot.captureSnapshot", {
            computedStyles: [],
            includePaintOrder: true,
            includeTextColorOpacities: false,
        });

        const doc = documents[0];
        const nodes = doc.nodes;
        const layout = doc.layout;

        const elements: InteractiveElement[] = [];

        if (!layout.nodeIndex || !layout.bounds) {
            return elements;
        }

        const viewportSize = await page.evaluate(() => ({
            width: window.innerWidth,
            height: window.innerHeight,
        }));

        let idCounter = 1;
        for (let i = 0; i < layout.nodeIndex.length; i++) {
            const nodeIdx = layout.nodeIndex[i];

            // CDP layout.bounds is an array of [x, y, width, height] arrays or flat based on protocol version
            // Let's force type it as any for extraction to handle playwright cdp version quirks
            const boundsVec = layout.bounds as any;

            // Sometimes it's a flat array of numbers, sometimes array of arrays
            let x, y, w, h;
            if (boundsVec[i] && typeof boundsVec[i][0] === "number") {
                [x, y, w, h] = boundsVec[i];
            } else {
                if ((i * 4 + 3) >= boundsVec.length) continue;
                x = boundsVec[i * 4];
                y = boundsVec[i * 4 + 1];
                w = boundsVec[i * 4 + 2];
                h = boundsVec[i * 4 + 3];
            }

            if (w === 0 || h === 0) continue;

            if (x < 0 || y < 0 || x > viewportSize.width || y > viewportSize.height) {
                continue;
            }

            const nodeNameIdx = nodes.nodeName ? nodes.nodeName[nodeIdx] : -1;
            const nodeName = nodeNameIdx >= 0 ? strings[nodeNameIdx]?.toLowerCase() : "";

            const isInteractiveTag = ["button", "input", "a", "select", "textarea"].includes(nodeName);

            if (isInteractiveTag) {
                const backendNodeId = nodes.backendNodeId ? nodes.backendNodeId[nodeIdx] : 0;
                const nodeValueIdx = nodes.nodeValue ? nodes.nodeValue[nodeIdx] : -1;

                // `inputValue` in CDP is a RareStringData interface: { index: number[], value: number[] }
                let inputValueStr = "";
                if (nodes.inputValue && nodes.inputValue.index) {
                    const rareStringIdx = nodes.inputValue.index.indexOf(nodeIdx);
                    if (rareStringIdx !== -1) {
                        const valIdx = nodes.inputValue.value[rareStringIdx];
                        inputValueStr = strings[valIdx] || "";
                    }
                }

                elements.push({
                    id: idCounter++,
                    backendNodeId,
                    type: nodeName,
                    name: nodeValueIdx >= 0 ? strings[nodeValueIdx] : "Unknown",
                    value: inputValueStr,
                    rect: { x, y, width: w, height: h }
                });
            }
        }

        // Update the cache
        activeCache = {
            hash: currentHash,
            url: currentUrl,
            elements,
            timestamp: now,
        };

        return elements;

    } finally {
        // Edge case fix from user: Memory leaks from unclosed sessions
        await cdp.detach().catch(() => { });
    }
}
