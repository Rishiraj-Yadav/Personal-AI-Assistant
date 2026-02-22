/**
 * Browser Agent HTTP Server
 * Exposes the Taskmaster browser automation engine via HTTP API.
 * Mirrors the desktop-agent architecture for symmetry.
 */
import express, { Request, Response, NextFunction } from "express";
import chalk from "chalk";
import process from "process";
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { resolveConfig } from "./core/config.js";
import { Taskmaster } from "./core/runner.js";
import { browserController } from "./tools/definitions.js";
import { setConfirmationSkip } from "./tools/definitions.js";

// ─── Configuration ───────────────────────────────────────────────────────────
const PORT = parseInt(process.env.BROWSER_AGENT_PORT || "4000", 10);
const HOST = process.env.BROWSER_AGENT_HOST || "127.0.0.1";

// API Key – generate one on startup and save to config/api_key.txt
const API_KEY = process.env.BROWSER_AGENT_API_KEY || crypto.randomBytes(24).toString("base64url");

function saveApiKey() {
  const configDir = path.resolve(process.cwd(), "config");
  if (!fs.existsSync(configDir)) fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(path.join(configDir, "api_key.txt"), API_KEY);
}

// ─── Express App ─────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

// Auth middleware
function verifyApiKey(req: Request, res: Response, next: NextFunction) {
  const key = req.headers["x-api-key"] as string;
  if (!key || key !== API_KEY) {
    res.status(401).json({ error: "Invalid or missing API key" });
    return;
  }
  next();
}

// ─── Task log buffer (for streaming back to caller) ──────────────────────────
interface TaskLog {
  agent: string;
  message: string;
  timestamp: string;
}

// ─── Routes ──────────────────────────────────────────────────────────────────

app.get("/", (_req: Request, res: Response) => {
  res.json({
    service: "Browser Agent",
    version: "3.0.0",
    status: "running",
    port: PORT,
  });
});

app.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "healthy",
    service: "browser-agent",
    browser_initialized: browserController !== null,
  });
});

/**
 * POST /execute
 * Body: { goal: string }
 * Returns: { success, status, logs[] }
 *
 * This is the main endpoint. The backend's browser_automation skill
 * calls this with the user's natural-language goal and gets back
 * the Taskmaster result plus a full log trail.
 */
app.post("/execute", verifyApiKey, async (req: Request, res: Response) => {
  const { goal } = req.body;

  if (!goal || typeof goal !== "string") {
    res.status(400).json({ error: "Missing required field: goal (string)" });
    return;
  }

  const logs: TaskLog[] = [];
  const originalLog = console.log;
  const originalError = console.error;

  // Intercept console output to capture Taskmaster logs
  const capture = (...args: any[]) => {
    const msg = args.map(String).join(" ");
    logs.push({ agent: "TASKMASTER", message: msg, timestamp: new Date().toISOString() });
    originalLog(...args);
  };
  console.log = capture as any;
  console.error = ((...args: any[]) => {
    const msg = args.map(String).join(" ");
    logs.push({ agent: "ERROR", message: msg, timestamp: new Date().toISOString() });
    originalError(...args);
  }) as any;

  try {
    const taskmaster = new Taskmaster(`api_task_${Date.now()}`);
    const status = await taskmaster.executeGoal(goal);

    // Restore console
    console.log = originalLog;
    console.error = originalError;

    res.json({
      success: status === "SUCCESS",
      status,
      goal,
      logs,
    });
  } catch (err: any) {
    console.log = originalLog;
    console.error = originalError;

    logs.push({ agent: "ERROR", message: err.message, timestamp: new Date().toISOString() });

    res.status(500).json({
      success: false,
      status: "ERROR",
      goal,
      error: err.message,
      logs,
    });
  }
});

app.post("/close", verifyApiKey, async (_req: Request, res: Response) => {
  await browserController.close();
  res.json({ success: true, message: "Browser closed" });
});

// ─── Startup ─────────────────────────────────────────────────────────────────

async function main() {
  // Resolve config (loads .env, validates API keys for LLM providers)
  try {
    resolveConfig();
  } catch (err: any) {
    console.error(chalk.red("Config Error:"), err.message);
    process.exit(1);
  }

  // Skip confirmation prompts when running as a server (no stdin)
  setConfirmationSkip(true);

  // Save API key for backend to read
  saveApiKey();

  // Initialize browser (headless: false for demo)
  try {
    await browserController.init();
  } catch (err: any) {
    console.error(chalk.red("Failed to initialize browser:"), err.message);
    process.exit(1);
  }

  app.listen(PORT, HOST, () => {
    console.log("\n" + "=".repeat(60));
    console.log(chalk.bgGreen.white.bold(" 🌐 BROWSER AGENT SERVICE "));
    console.log("=".repeat(60));
    console.log(`Version:  3.0.0`);
    console.log(`Host:     ${HOST}:${PORT}`);
    console.log(`API Key:  ${API_KEY.slice(0, 20)}...`);
    console.log(`Key file: config/api_key.txt`);
    console.log("=".repeat(60));
    console.log(chalk.yellow("⚠️  Browser is visible (headless: false)"));
    console.log(chalk.gray("Press Ctrl+C to stop"));
    console.log("=".repeat(60) + "\n");
  });
}

main();
