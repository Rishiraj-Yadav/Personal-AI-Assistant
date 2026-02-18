import { generateText, tool } from "ai";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { config } from "./config.js";
import { tools } from "./tools.js";

// Initialize Provider
const google = createGoogleGenerativeAI({
    apiKey: config.GOOGLE_API_KEY || "",
});

export class AgentRunner {
    private model: any;

    constructor() {
        if (!config.GOOGLE_API_KEY) {
            console.warn("⚠️ WARNING: GOOGLE_API_KEY is not set. AI features will not work.");
        } else {
            console.log(`🔑 API Key loaded: ${config.GOOGLE_API_KEY.substring(0, 5)}...`);
        }
        this.model = google("models/gemini-1.5-flash" as any);
    }

    async run(input: string) {
        try {
            const { text } = await generateText({
                model: this.model,
                system: "You are a browser automation agent. You can navigate, click, type, and read text. Use the provided tools to fulfill the user's request. If you need to search, navigate to google.com first.",
                prompt: input,
                tools: tools as any,
                maxSteps: 5, // Allow up to 5 steps for multi-turn actions
                onStepFinish: (step: any) => {
                    console.log(`> Steps: ${JSON.stringify(step.toolCalls.map((tc: any) => tc.toolName))}`);
                }
            } as any);

            return text;
        } catch (error: any) {
             console.error("Agent Error:", error);
             return `Error: ${error.message}`;
        }
    }
}
