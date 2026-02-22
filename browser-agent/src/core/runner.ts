import { generateText } from "ai";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createGroq } from "@ai-sdk/groq";
import { DB } from "./db.js";
import { runPlanner, runVision, runAction, runVerifier } from "./agents.js";
import { browserController } from "../tools/definitions.js";
import { invalidateCache } from "../tools/cdpObserver.js";
import { resolveConfig } from "./config.js";
import chalk from "chalk";

const MAX_EXECUTION_TIME_MS = 270000; // 4.5 minutes Vercel bailout

// Keep track of tasks across the CLI session so the agent remembers what it just did
const globalSessionTasks: string[] = [];

export class Taskmaster {
  private taskId: string;
  private startTime: number;
  private config = resolveConfig();

  constructor(taskId: string = "default_task") {
    this.taskId = taskId;
    this.startTime = Date.now();
  }

  private log(agent: string, message: string) {
    if (this.config.verbose) {
      const colors: any = {
        PLANNER: chalk.blue,
        VISION: chalk.magenta,
        ACTION: chalk.green,
        VERIFIER: chalk.yellow,
        SYSTEM: chalk.gray
      };
      const colorize = colors[agent] || chalk.white;
      console.log(colorize(`[${agent}] ${message}`));
    }
    DB.logHistory(agent, message, {});
  }

  async executeGoal(userGoal: string) {
    this.log("SYSTEM", `Starting Taskmaster for goal: "${userGoal}"`);

    // 1. PLANNING PHASE
    let stepsArray = DB.getState(`plan_${this.taskId}`);
    if (!stepsArray) {
      this.log("PLANNER", "Drafting new Execution Plan...");
      const context = await browserController.getPageContext();
      const planResult = await runPlanner(userGoal, context, globalSessionTasks);
      stepsArray = planResult.object.steps;
      DB.setState(`plan_${this.taskId}`, stepsArray);
      DB.recordSteps(this.taskId, stepsArray);
      this.log("PLANNER", `Plan generated: ${stepsArray.length} steps. Context: [${context.title}]`);
    }

    // 2. EXECUTION LOOP
    for (let i = 0; i < stepsArray.length; i++) {
      const currentStep = stepsArray[i];
      this.log("SYSTEM", `--- Executing Step ${i + 1}/${stepsArray.length}: ${currentStep} ---`);

      let stepComplete = false;
      let retryCount = 0;
      let actionHistoryStr = "";

      while (!stepComplete && retryCount < 5) {
        // Check Vercel Timeout Bailout
        if (Date.now() - this.startTime > MAX_EXECUTION_TIME_MS) {
          this.log("SYSTEM", "Approaching 270s execution limit. Bailing out gracefully for chunked resumption.");
          return "CHUNK_COMPLETE";
        }

        try {
          // A. VISION PHASE
          this.log("VISION", "Capturing screenshot and CDP registry...");
          const { screenshotPath, elements } = await browserController.captureVisionState();

          const elementRegistryString = JSON.stringify(elements.map(e => ({ id: e.id, type: e.type, name: e.name, value: e.value })), null, 2);

          this.log("VISION", "Analyzing multi-modal state...");
          const visionContext = await runVision(screenshotPath, elementRegistryString, currentStep);

          const visionStateDump = JSON.stringify(visionContext.object, null, 2);
          this.log("VISION", `Found ${visionContext.object.elements.length} primary targets. Summary: ${visionContext.object.page_summary}`);

          // B. ACTION PHASE
          this.log("ACTION", `Determining next move...`);
          let actResult;
          try {
            const actObject = await runAction(currentStep, visionStateDump, actionHistoryStr);
            actResult = actObject.object;
          } catch (zodError) {
            this.log("ACTION", "Zod parsing failed. Attempting regex fallback.");
            // Fallback Regex processing logic would go here if needed. Throw for now.
            throw new Error("Action LLM drifted from JSON schema.");
          }

          this.log("ACTION", `Exec: ${actResult.actionType.toUpperCase()} | Reason: ${actResult.reason}`);

          let actionDescription = `${actResult.actionType}`;

          if (actResult.actionType === "navigate" && actResult.textInput) {
            await browserController.navigate(actResult.textInput);
            actionDescription += ` to ${actResult.textInput}`;
          } else if (actResult.actionType === "done") {
            stepComplete = true;
            break;
          } else if (actResult.targetId !== undefined) {
            const targetEl = elements.find(e => e.id === actResult.targetId);
            if (!targetEl) throw new Error(`ActionAgent provided invalid ID: ${actResult.targetId}`);

            if (actResult.actionType === "click") {
              await browserController.click(targetEl);
              actionDescription += ` on ID ${targetEl.id} (${targetEl.name})`;
            } else if (actResult.actionType === "type" && actResult.textInput !== undefined) {
              await browserController.type(targetEl, actResult.textInput);
              actionDescription += ` "${actResult.textInput}" into ID ${targetEl.id}`;
            }
          } else if (actResult.actionType === "press" && actResult.keyPress) {
            await browserController.press(actResult.keyPress);
            actionDescription += ` key ${actResult.keyPress}`;
          }

          // C. VERIFICATION PHASE (Small delay to let DOM settle)
          await new Promise(r => setTimeout(r, 2000));
          this.log("VERIFIER", "Evaluating outcome...");

          const postActionState = await browserController.captureVisionState();
          const verifyResult = await runVerifier(actionDescription, currentStep, JSON.stringify(postActionState.elements.map(e => e.name)));

          this.log("VERIFIER", `Decision: ${verifyResult.object.status.toUpperCase()} | Reason: ${verifyResult.object.reason}`);

          actionHistoryStr += `Tried Action: ${actionDescription}\nVerifier Feedback: ${verifyResult.object.status.toUpperCase()} - ${verifyResult.object.reason}\n\n`;

          if (verifyResult.object.status === "success" || verifyResult.object.status === "task_complete") {
            stepComplete = true;
            DB.updateStepStatus(this.taskId, i + 1, "SUCCESS");
          } else if (verifyResult.object.status === "retry_vision") {
            this.log("SYSTEM", "Invalidating Vision Cache and retrying step due to DOM shift...");
            invalidateCache(); // Blast the DOM hash cache
            retryCount++;
          } else {
            this.log("VERIFIER", "Action failed. Retrying...");
            retryCount++;
          }

        } catch (err: any) {
          this.log("SYSTEM", `Agent Error executing step: ${err.message}`);
          retryCount++;
          await new Promise(r => setTimeout(r, 2000));
        }
      }

      if (!stepComplete) {
        this.log("SYSTEM", `Failed to complete step '${currentStep}' after 3 retries. Aborting task.`);
        DB.updateStepStatus(this.taskId, i + 1, "FAILED");
        globalSessionTasks.push(`[FAILED] ${userGoal}`);
        return "FAILED";
      }
    }

    this.log("SYSTEM", "Taskmaster Goal Successfully Completed.");
    globalSessionTasks.push(`[SUCCESS] ${userGoal}`);
    return "SUCCESS";
  }
}
