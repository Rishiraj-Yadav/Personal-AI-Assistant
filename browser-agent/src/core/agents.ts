import { resolveConfig } from "./config.js";
import process from "process";
import axios from "axios";
import fs from "fs";

// Configure discrete models based on config
const config = resolveConfig();
// E.g., Use "pro" for complex reasoning (Planner, Vision), "flash" for quick execution (Action, Verifier)
const proModel = "gemini-2.5-pro";
const flashModel = "gemini-2.5-flash"; // Override config for stability while debugging

async function geminiFetch(modelId: string, systemPrompt: string, userContent: any[], temperature: number = 0.1) {
    const apiKey = process.env.GOOGLE_API_KEY;
    if (!apiKey) throw new Error("GOOGLE_API_KEY is not set.");

    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`;

    const payload = {
        systemInstruction: { parts: [{ text: systemPrompt }] },
        contents: [
            { role: "user", parts: userContent }
        ],
        generationConfig: { temperature }
    };

    try {
        const response = await axios.post(endpoint, payload);
        const textResponse = response.data.candidates[0].content.parts[0].text;
        return textResponse;
    } catch (err: any) {
        console.error("Gemini API Error:", err.response?.data || err.message);
        throw err;
    }
}

// ─── 1. Planner Agent ────────────────────────────────────────────────────────
const plannerPrompt = `You are the PLANNER AGENT for a web browser automation system.
Your job is to break down a high-level user request into concrete, atomic browser steps.

Available actions:
- navigate: Go to a specific URL
- interact: Click, type, or interact with an element on the active page
- extract: Read information from the active page

CONTEXT RULES:
- You will be given the CURRENT URL and PAGE TITLE.
- Use this context! If the user says "search for X", and you are ALREADY on youtube.com, DO NOT navigate to Google. Instruct the Action agent to interact with the search bar on the CURRENT page instead.
- If the goal implies navigating to a new site, then emit a 'navigate' action.

OUTPUT RULES:
- Output MUST strictly be a JSON array of step strings.
- Example: ["Navigate to wikipedia.org", "Interact: find the search bar and type 'Artificial Intelligence'", "Interact: hit enter or click search"]
- Do not output markdown code blocks. Just the raw JSON array.
`;

export async function runPlanner(userGoal: string, pageContext: { url: string; title: string }, previousGoals: string[]) {
    let contextStr = `Current URL: ${pageContext.url}\nCurrent Page Title: ${pageContext.title}\n`;
    if (previousGoals.length > 0) {
        contextStr += `Past Goals In This Session:\n${previousGoals.map((g, i) => `${i + 1}. ${g}`).join("\n")}\n`;
    }

    const resText = await geminiFetch(proModel, plannerPrompt, [
        { text: `${contextStr}\nNew Goal: ${userGoal}` }
    ]);

    try {
        const steps = JSON.parse(resText.replace(/```json/g, "").replace(/```/g, "").trim());
        return { object: { steps } };
    } catch (e) {
        console.error("Planner JSON parse fallback error: " + resText);
        throw e;
    }
}

// ─── 2. Vision Agent ─────────────────────────────────────────────────────────

const visionPrompt = `You are the VISION AGENT. 
You are given a multimodal screenshot of a web page and a JSON registry of interactive element bounding boxes.

Your job is to act as the eyes of the ActionAgent. The ActionAgent cannot see the page; it only knows the numeric IDs you give it.

OUTPUT RULES:
- Analyze the screenshot and the provided JSON registry.
- Identify the most useful, prominent interactive elements (search bars, primary buttons, main links).
- Extract their precise numeric 'id' from the registry.
- Return a strict JSON response containing an 'elements' array with matching IDs and descriptions, and a 'page_summary' string.
- Your output must be a standard JSON string payload. No markdown wrappers. Example structure: {"elements": [ {"id": 1, "description": "Search input box", "actionability": "typable"} ], "page_summary": "Looking at the Wikipedia homepage."}
`;

export async function runVision(screenshotPath: string, elementRegistryData: string, taskContext: string) {
    const buffer = fs.readFileSync(screenshotPath);
    const base64Image = buffer.toString("base64");

    const contentParts = [
        { text: `Current Task Context: ${taskContext}\n\nElement Bounding Box Registry:\n${elementRegistryData}` },
        { inlineData: { mimeType: "image/png", data: base64Image } }
    ];

    const resText = await geminiFetch(proModel, visionPrompt, contentParts, 0.0);

    try {
        const payload = JSON.parse(resText.replace(/```json/g, "").replace(/```/g, "").trim());
        return { object: payload };
    } catch (e) {
        console.error("Vision JSON parse fallback error: " + resText);
        throw e;
    }
}

// ─── 3. Action Agent ─────────────────────────────────────────────────────────

const actionPrompt = `You are the ACTION AGENT.
You execute immediate, precise commands based on the current step plan and the Vision Agent's element list.

RULES:
- You DO NOT see the web page. You only see the text list of elements provided by the Vision Agent.
- If the current step says to 'type', emit a 'type' action for the 'targetId' that matches the best input box.
- If the current step says to 'navigate', emit 'navigate' and put the URL in 'textInput'.
- If the current step is completely fulfilled or we have reached the final goal, emit 'done'.
- Return strict JSON ONLY with { "actionType": "...", "reason": "...", "targetId": number (optional), "textInput": "..." (optional), "keyPress": "..." (optional) }
- Do not output markdown code blocks.
`;

export async function runAction(currentStep: string, visionState: string, actionHistory: string = "") {
    const historyContext = actionHistory ? `\n\nPREVIOUS ACTIONS THIS STEP & FEEDBACK:\n${actionHistory}\n(Do not repeat failed actions. If you typed, you likely need to 'press' Enter next.)` : "";

    const resText = await geminiFetch(flashModel, actionPrompt, [
        { text: `Current Step to fullfil: ${currentStep}\n\nVision Profile of Active Page:\n${visionState}${historyContext}` }
    ]);

    try {
        const payload = JSON.parse(resText.replace(/```json/g, "").replace(/```/g, "").trim());
        return { object: payload };
    } catch (e) {
        console.error("Action JSON parse fallback error: " + resText);
        throw e;
    }
}

// ─── 4. Verifier Agent ───────────────────────────────────────────────────────

const verifierPrompt = `You are the VERIFIER AGENT.
Your job is to look at the result of the LAST action and the CURRENT page state, and decide if the ActionAgent successfully accomplished the 'Current Step'.

RULES:
- If the action clearly advanced the task (e.g., URL changed, new results appeared), return 'success'.
- If the action failed (e.g., clicked a dead link, nothing happened), return 'fail'.
- If the page visually updated but we lost the element tracking (e.g. a scroll event or SPA pop-up happened), return 'retry_vision' to trigger a new screenshot.
- If the overall user goal has been met, return 'task_complete'.
- Return strict JSON ONLY with {"status": "success"|"fail"|"retry_vision"|"task_complete", "reason": "..."}
- NO MARKDOWN SYNTAX.
`;

export async function runVerifier(actionTaken: string, previousStep: string, newPageStateContext: string) {
    const resText = await geminiFetch(flashModel, verifierPrompt, [
        { text: `Goal Step: ${previousStep}\n\nAction that was taken: ${actionTaken}\n\nNew Page State:\n${newPageStateContext}` }
    ]);

    try {
        const payload = JSON.parse(resText.replace(/```json/g, "").replace(/```/g, "").trim());
        return { object: payload };
    } catch (e) {
        console.error("Verifier JSON parse fallback error: " + resText);
        throw e;
    }
}
