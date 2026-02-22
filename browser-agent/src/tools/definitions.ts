import { tool } from "ai";
import { z } from "zod";
import fs from "fs/promises";
import path from "path";
import { exec } from "child_process";
import { promisify } from "util";
import * as readline from "readline";
import process from "process";
// import { getAccessibilityTree, formatTreeAsText } from "./screenObserver.js";
import { think } from "./think.js";

const execAsync = promisify(exec);

// This flag is set from config at runtime via setConfirmationRequired()
let skipConfirmation = false;

export function setConfirmationSkip(skip: boolean) {
  skipConfirmation = skip;
}

async function askForConfirmation(actionDescription: string): Promise<boolean> {
  if (skipConfirmation) return true;

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise((resolve) => {
    rl.question(
      `\n⚠️  SAFETY ALERT: Agent wants to ${actionDescription}\n   Allow this action? (y/N): `,
      (answer) => {
        rl.close();
        resolve(answer.toLowerCase().trim() === "y");
      }
    );
  });
}

// Output truncation limit — read from env or default
const MAX_OUTPUT = parseInt(process.env.TP_MAX_OUTPUT || "4000", 10);

function truncate(text: string, limit: number = MAX_OUTPUT): string {
  if (text.length > limit) {
    return text.slice(0, limit) + `\n...[Truncated (total ${text.length} chars)]...`;
  }
  return text;
}

// ─── Tool Definitions ───────────────────────────────────────────────────────

export const readFile = tool({
  description: "Read a file from the filesystem",
  parameters: z.object({
    filePath: z.string().describe("Path to the file to read"),
  }),
  execute: async ({ filePath }: { filePath: string }) => {
    try {
      const content = await fs.readFile(filePath, "utf-8");
      return truncate(content);
    } catch (error: any) {
      return `Error reading file: ${error.message}`;
    }
  },
} as any) as any;

export const writeFile = tool({
  description: "Write content to a file",
  parameters: z.object({
    filePath: z.string().describe("Path to the file to write"),
    content: z.string().describe("Content to write to the file"),
  }),
  execute: async ({ filePath, content }: { filePath: string; content: string }) => {
    try {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, content, "utf-8");
      return `Successfully wrote to ${filePath}`;
    } catch (error: any) {
      return `Error writing file: ${error.message}`;
    }
  },
} as any) as any;

export const ls = tool({
  description: "List files in a directory",
  parameters: z.object({
    dirPath: z
      .string()
      .optional()
      .describe("Directory path to list (defaults to current directory)"),
  }),
  execute: async ({ dirPath }: { dirPath?: string }) => {
    const targetDir = dirPath || ".";
    try {
      const files = await fs.readdir(targetDir);
      return files.join("\n");
    } catch (error: any) {
      return `Error listing directory: ${error.message}`;
    }
  },
} as any) as any;

// Desktop tools removed for browser agent specialization


// Input tools removed for browser agent specialization


// ─── Browser Controller (Taskmaster Engine) ──────────────────────────────────
import { extractInteractiveElements, InteractiveElement } from "./cdpObserver.js";

export class BrowserController {
  private browser: any = null;
  private context: any = null;
  private page: any = null;

  async init(cdpUrl?: string) {
    if (this.browser) return;
    const { chromium } = await import("playwright-core");

    if (cdpUrl) {
      console.log(`🔗 Connecting to existing browser via CDP: ${cdpUrl}`);
      try {
        this.browser = await chromium.connectOverCDP(cdpUrl);
        const contexts = this.browser.contexts();
        this.context = contexts.length > 0 ? contexts[0] : await this.browser.newContext();
        const pages = this.context.pages();
        this.page = pages.length > 0 ? pages[0] : await this.context.newPage();
      } catch (err: any) {
        console.error(`❌ Failed to connect to CDP at ${cdpUrl}:`, err.message);
        throw new Error(`CDP Connection failed: ${err.message}`);
      }
    } else {
      console.log("Launching Brave browser...");
      this.browser = await chromium.launch({
        headless: false,
        executablePath: "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
      });
      this.context = await this.browser.newContext({
        viewport: { width: 1024, height: 768 } // Recommended Vision dimensions
      });
      this.page = await this.context.newPage();
    }
  }

  async close() {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
      this.context = null;
      this.page = null;
    }
  }

  async navigate(url: string) {
    if (!this.page) await this.init();
    await this.page.goto(url, { waitUntil: "domcontentloaded" });
  }

  async getPageContext(): Promise<{ url: string; title: string }> {
    if (!this.page) return { url: "about:blank", title: "New Tab" };
    try {
      const url = this.page.url();
      const title = await this.page.title();
      return { url, title };
    } catch (err) {
      return { url: "unknown", title: "unknown" };
    }
  }

  private async _click(element: InteractiveElement) {
    const centerX = element.rect.x + (element.rect.width / 2);
    const centerY = element.rect.y + (element.rect.height / 2);
    const scroll = await this.page.evaluate(() => ({ x: window.scrollX, y: window.scrollY }));
    await this.page.mouse.click(centerX - scroll.x, centerY - scroll.y, { force: true });
  }

  async click(element: InteractiveElement) {
    if (!this.page) return;
    const allowed = await askForConfirmation(`BROWSER CLICK: ID ${element.id} (${element.name})`);
    if (!allowed) throw new Error("Action denied by user.");
    await this._click(element);
  }

  async type(element: InteractiveElement, text: string) {
    if (!this.page) return;
    const allowed = await askForConfirmation(`BROWSER TYPE: "${text}" into ID ${element.id} (Will press Enter)`);
    if (!allowed) throw new Error("Action denied by user.");

    await this._click(element); // Focus without an additional safety prompt

    // Clear the input field first in case there is old text
    await this.page.keyboard.press("Control+A");
    await this.page.keyboard.press("Backspace");

    await this.page.keyboard.type(text, { delay: 50 });

    // Always press enter after typing to forcefully submit the value
    await this.page.keyboard.press("Enter");
  }

  async press(key: string) {
    if (!this.page) return;
    await this.page.keyboard.press(key);
  }

  async captureVisionState(): Promise<{ screenshotPath: string, elements: InteractiveElement[] }> {
    if (!this.page) await this.init();

    // 1. Get elements via CDP
    const elements = await extractInteractiveElements(this.page);

    // 2. Take screenshot of the exact viewport matching the elements
    const fname = `vision_${Date.now()}.png`;
    const filepath = path.resolve(process.cwd(), "data", fname);
    await this.page.screenshot({ path: filepath });

    return { screenshotPath: filepath, elements };
  }
}

/** Legacy tools for Planner/Agent direct file interaction if needed */
export const legacyTools = {
  readFile,
  writeFile,
  ls,
  think,
};

export const browserController = new BrowserController();
