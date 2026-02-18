import { tool } from "ai";
import { z } from "zod";
import * as actions from "./actions.js";

export const navigate = tool({
    description: "Navigate to a specific URL",
    parameters: z.object({
        url: z.string().describe("The URL to navigate to"),
    }),
    execute: async ({ url }: { url: string }) => {
        try {
            console.log(`> Navigating to ${url}...`);
            const result = await actions.navigate(url);
            return JSON.stringify(result);
        } catch (error: any) {
            return `Error navigating: ${error.message}`;
        }
    },
} as any);

export const screenshot = tool({
    description: "Take a screenshot of the current page",
    parameters: z.object({
        path: z.string().optional().describe("The execution path to save the screenshot. Defaults to screenshot.png"),
    }),
    execute: async ({ path }: { path?: string }) => {
        try {
            const actualPath = path || "screenshot.png";
            console.log(`> Taking screenshot to ${actualPath}...`);
            const result = await actions.screenshot(actualPath);
            return JSON.stringify(result);
        } catch (error: any) {
            return `Error taking screenshot: ${error.message}`;
        }
    },
} as any);

export const click = tool({
    description: "Click an element on the page",
    parameters: z.object({
        selector: z.string().describe("The CSS selector of the element to click"),
    }),
    execute: async ({ selector }: { selector: string }) => {
        try {
            console.log(`> Clicking ${selector}...`);
            const result = await actions.click(selector);
            return JSON.stringify(result);
        } catch (error: any) {
            return `Error clicking: ${error.message}`;
        }
    },
} as any);

export const type = tool({
    description: "Type text into an input field",
    parameters: z.object({
        selector: z.string().describe("The CSS selector of the input field"),
        text: z.string().describe("The text to type"),
    }),
    execute: async ({ selector, text }: { selector: string; text: string }) => {
        try {
            console.log(`> Typing "${text}" into ${selector}...`);
            const result = await actions.type(selector, text);
            return JSON.stringify(result);
        } catch (error: any) {
            return `Error typing: ${error.message}`;
        }
    },
} as any);

export const getText = tool({
    description: "Get text content from an element",
    parameters: z.object({
        selector: z.string().describe("The CSS selector of the element"),
    }),
    execute: async ({ selector }: { selector: string }) => {
        try {
            console.log(`> Reading text from ${selector}...`);
            const result = await actions.getText(selector);
            return JSON.stringify({ text: result ?? null });
        } catch (error: any) {
            return `Error reading text: ${error.message}`;
        }
    },
} as any);

export const tools = {
    navigate,
    screenshot,
    click,
    type,
    getText
};
