import { Command } from "commander";
import chalk from "chalk";
import process from "process";
import * as readline from "readline";
import { resolveConfig, AppConfig } from "./core/config.js";
import { Taskmaster } from "./core/runner.js";
import { browserController } from "./tools/definitions.js";

const program = new Command();

program
  .name("tp-agent")
  .description("Multi-Agent Web Automation framework using Taskmaster")
  .version("3.0.0")
  .option("--provider <name>", "LLM provider: groq | google", undefined)
  .option("--model <name>", "Model name (e.g. llama-3.3-70b-versatile, gemini-2.0-flash)")
  .option("--verbose", "Show debug output (tool args, results, etc.)")
  .option("--cwd <path>", "Override working directory")
  .action(async (opts) => {
    const cliOpts: Partial<AppConfig> = {};

    if (opts.provider) cliOpts.provider = opts.provider;
    if (opts.model) cliOpts.model = opts.model;
    if (opts.verbose) cliOpts.verbose = true;
    if (opts.cwd) cliOpts.cwd = opts.cwd;

    let config: AppConfig;
    try {
      config = resolveConfig(cliOpts);
    } catch (error: any) {
      console.error(chalk.red("Config Error:"), error.message);
      process.exit(1);
    }

    console.clear();
    console.log(chalk.bgBlueBright.white.bold(" TP Taskmaster v3.0 "));
    console.log(chalk.gray(`Target Environment: ${config.provider}`));
    console.log();

    try {
      await browserController.init();
    } catch (err: any) {
      console.error(chalk.red("Failed to initialize remote browser:"), err.message);
      process.exit(1);
    }

    await startCli();
  });

async function startCli() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const question = (q: string): Promise<string> =>
    new Promise((resolve) => {
      rl.question(q, (ans: string) => resolve(ans));
    });

  while (true) {
    let input = "";
    try {
      input = await question(chalk.green("Goal: "));
    } catch {
      process.exit(0);
    }

    if (!input.trim()) continue;
    if (input.toLowerCase() === "exit" || input.toLowerCase() === "quit") {
      console.log("Goodbye!");
      await browserController.close();
      process.exit(0);
    }

    // Close rl so tools that need stdin (confirmations) can use it
    rl.close();

    try {
      // Execute the multi-agent task state machine
      const taskmaster = new Taskmaster(`cli_task_${Date.now()}`);
      const response = await taskmaster.executeGoal(input);
      console.log(chalk.blue("\nTaskmaster Status:"), response);
    } catch (error: any) {
      console.error(chalk.red("Error:"), error.message);
    }

    console.log(); // blank line between turns

    // Recurse to recreate rl interface
    return startCli();
  }
}

program.parse(process.argv);
