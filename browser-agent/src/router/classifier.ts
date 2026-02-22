import { generateText } from "ai";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { AppConfig } from "../core/config.js";

// We use a lightweight model for classification
const CLASSIFIER_MODEL = "gemini-flash-latest";

export interface Intent {
  type: "simple" | "reasoning" | "coding" | "creative";
  reasoning: string;
  recommendedModel?: string;
  thinkingLevel: "off" | "low" | "high";
}

export async function classifyIntent(
  input: string,
  config: AppConfig
): Promise<Intent> {
  try {
    const google = createGoogleGenerativeAI({
      apiKey: process.env.GOOGLE_API_KEY!,
    });
    const model = google(CLASSIFIER_MODEL);

    const prompt = `
You are an intent classifier for an AI agent.
Analyze the user's request and categorize it into one of the following types:
- "simple": Greetings, small talk, simple fact checks, simple lookups.
- "reasoning": Math, logic puzzles, multi-step plans, analysis.
- "coding": Writing code, debugging, refactoring, explaining code.
- "creative": Writing stories, poems, emails, creative content.

Respond with a JSON object ONLY:
{
  "type": "simple" | "reasoning" | "coding" | "creative",
  "reasoning": "Brief explanation of why",
  "thinkingLevel": "off" | "low" | "high"
}

User Request: "${input}"
    `;

    const result = await generateText({
      model,
      messages: [{ role: "user", content: prompt }],
      temperature: 0,
    });

    const text = result.text.replace(/```json/g, "").replace(/```/g, "").trim();
    const intent = JSON.parse(text) as Intent;
    
    // Map intent to model recommendations
    if (intent.type === "reasoning" || intent.type === "coding") {
      intent.recommendedModel = "gemini-flash-latest"; // Or config.thinkingModel
      intent.thinkingLevel = "high";
    } else if (intent.type === "creative") {
      intent.recommendedModel = "gemini-flash-latest";
      intent.thinkingLevel = "low";
    } else {
      intent.recommendedModel = "gemini-flash-latest";
      intent.thinkingLevel = "off";
    }

    return intent;

  } catch (error) {
    console.error("Classification failed, defaulting to simple:", error);
    return {
      type: "simple",
      reasoning: "Classification failed",
      thinkingLevel: "low",
      recommendedModel: "gemini-flash-latest",
    };
  }
}
