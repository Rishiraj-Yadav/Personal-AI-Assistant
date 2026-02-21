import dotenv from "dotenv";
import path from "path";
import process from "process";
import fs from "fs";

dotenv.config({ path: path.resolve(process.cwd(), ".env") });

export interface AppConfig {
  provider: "groq" | "google";
  model: string;
  maxTokens: number;
  maxSteps: number;
  temperature: number;
  noConfirm: boolean;
  verbose: boolean;
  cwd: string;
  systemPromptFile?: string;
  thinking: "off" | "low" | "high";
  smart: boolean;
}

/** Default model per provider — only used if nothing is specified via CLI or env */
const DEFAULT_MODELS: Record<string, string> = {
  groq: "llama-3.3-70b-versatile",
  google: "gemini-1.5-flash",
};

function envBool(key: string, fallback: boolean): boolean {
  const val = process.env[key];
  if (!val) return fallback;
  return val === "true" || val === "1";
}

function envInt(key: string, fallback: number): number {
  const val = process.env[key];
  if (!val) return fallback;
  const n = parseInt(val, 10);
  return Number.isNaN(n) ? fallback : n;
}

function envFloat(key: string, fallback: number): number {
  const val = process.env[key];
  if (!val) return fallback;
  const n = parseFloat(val);
  return Number.isNaN(n) ? fallback : n;
}

/**
 * Merge CLI options → env vars → defaults.
 * CLI options take highest priority, then env vars, then built-in defaults.
 */
export function resolveConfig(cliOpts: Partial<AppConfig> = {}): AppConfig {
  const provider =
    cliOpts.provider ??
    (process.env.TP_PROVIDER as "groq" | "google" | undefined) ??
    "google";

  const model =
    cliOpts.model ??
    process.env.TP_MODEL ??
    DEFAULT_MODELS[provider] ??
    "llama-3.3-70b-versatile";

  const config: AppConfig = {
    provider,
    model,
    maxTokens: cliOpts.maxTokens ?? envInt("TP_MAX_TOKENS", 4096),
    maxSteps: cliOpts.maxSteps ?? envInt("TP_MAX_STEPS", 10),
    temperature: cliOpts.temperature ?? envFloat("TP_TEMPERATURE", 0.7),
    noConfirm: cliOpts.noConfirm ?? envBool("TP_NO_CONFIRM", false),
    verbose: cliOpts.verbose ?? envBool("TP_VERBOSE", false),
    cwd: cliOpts.cwd ?? process.cwd(),
    systemPromptFile: cliOpts.systemPromptFile,
    thinking: cliOpts.thinking ?? (process.env.TP_THINKING as "off" | "low" | "high") ?? "low",
    smart: cliOpts.smart ?? envBool("TP_SMART", false),
  };

  // Validate API key exists for chosen provider
  if (provider === "google" && !process.env.GOOGLE_API_KEY) {
    throw new Error("GOOGLE_API_KEY is required in .env when using --provider google");
  }
  if (provider === "groq" && !process.env.GROQ_API_KEY) {
    throw new Error("GROQ_API_KEY is required in .env when using --provider groq");
  }

  return config;
}

/** Load custom system prompt from file if specified */
export function loadSystemPromptFile(filePath: string): string {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`System prompt file not found: ${resolved}`);
  }
  return fs.readFileSync(resolved, "utf-8");
}
