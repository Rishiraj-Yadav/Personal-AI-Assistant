import { z } from "zod";
import dotenv from "dotenv";

dotenv.config();

const ConfigSchema = z.object({
  HEADLESS: z.enum(["true", "false"]).transform((v) => v === "true").default("false"),
  BROWSER_TYPE: z.enum(["chromium", "firefox", "webkit"]).default("chromium"),
  USER_DATA_DIR: z.string().optional(),
  PROXY_SERVER: z.string().optional(),
  GOOGLE_API_KEY: z.string().optional(),
});

export const config = ConfigSchema.parse(process.env);
