import { tool } from "ai";
import { z } from "zod";
import chalk from "chalk";

export const think = tool({
  description:
    "Log a thought or internal monologue. Use this to plan, analyze, or reason about the next steps without taking any external action. This thought is visible to you (the agent) and the user, but does not affect the environment.",
  parameters: z.object({
    thought: z.string().optional().describe("The content of your thought or reasoning."),
  }),
  execute: async (args: any) => {
    // We log it to the console so the user sees it in real-time
    const thought = args.thought || args.reasoning || args.thinking || JSON.stringify(args);
    console.log(chalk.yellow(`\n💭 Thinking: ${thought}\n`));
    return `Thought recorded: ${thought}`;
  },
} as any) as any;
