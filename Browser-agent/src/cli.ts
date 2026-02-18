import { Command } from "commander";
import * as readline from "readline";
import { navigate, screenshot, click, type, getText } from "./actions.js";
import { closeBrowserSession, getBrowserSession } from "./session.js";

const program = new Command();

program
  .name("browser-agent")
  .description("Standalone Browser Agent CLI")
  .version("1.0.0");

async function handleCommand(input: string) {
    const [cmd, ...args] = input.trim().split(" ");
    
    try {
        switch (cmd) {
            case "navigate":
                if (!args[0]) {
                    console.log("Usage: navigate <url>");
                    return;
                }
                const navResult = await navigate(args[0]);
                console.log(JSON.stringify(navResult, null, 2));
                break;
            case "screenshot":
                const path = args[0] || "screenshot.png";
                const screenResult = await screenshot(path);
                console.log(JSON.stringify(screenResult, null, 2));
                break;
            case "click":
                if (!args[0]) {
                    console.log("Usage: click <selector>");
                    return;
                }
                const clickResult = await click(args[0]);
                console.log(JSON.stringify(clickResult, null, 2));
                break;
             case "type":
                if (!args[0] || !args[1]) {
                    console.log("Usage: type <selector> <text>");
                    return;
                }
                const typeResult = await type(args[0], args.slice(1).join(" "));
                console.log(JSON.stringify(typeResult, null, 2));
                break;
             case "text":
                if (!args[0]) {
                     console.log("Usage: text <selector>");
                     return;
                }
                const textResult = await getText(args[0]);
                console.log(textResult);
                break;
            case "exit":
            case "quit":
                console.log("Closing session...");
                await closeBrowserSession();
                process.exit(0);
                break;
            case "help":
                console.log("Available commands: navigate, screenshot, click, type, text, exit");
                break;
            case "":
                break;
            default:
                console.log(`Unknown command: ${cmd}. Type 'help' for available commands.`);
        }
    } catch (error) {
        console.error("Error executing command:", error);
    }
}

// ... imports
import { AgentRunner } from "./agent.js";
// ... existing imports

// ... existing code ...

program
  .command("interactive")
  .alias("chat")
  .description("Start interactive agent mode with Gemini AI (Vercel SDK)")
  .action(async () => {
    console.log("🤖 Browser Agent Interactive Mode (AI Powered 🧠)");
    console.log("Type 'help' for commands, 'exit' to quit.");
    
    // Initialize session immediately
    console.log("Initializing browser...");
    await getBrowserSession();
    
    console.log("Initializing AI Agent...");
    const runner = new AgentRunner();
    
    console.log("Ready! Ask me to do something.");

    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
        prompt: "agent> "
    });

    rl.prompt();

    rl.on("line", async (line) => {
        const input = line.trim();
        
        // Handle local commands first
        if (input === "exit" || input === "quit") {
             console.log("Closing session...");
             await closeBrowserSession();
             process.exit(0);
        } else if (input === "help") {
             console.log("Just type what you want to do in plain English.");
             console.log("Example: 'Go to google and search for openai'");
        } else if (input) {
            process.stdout.write("Thinking... ");
            const response = await runner.run(input);
            console.log("\n" + response);
        }
        
        rl.prompt();
    }).on("close", async () => {
        await closeBrowserSession();
        process.exit(0);
    });
  });

// ... existing code ...

program
  .command("navigate")
  .description("Navigate to a URL")
  .argument("<url>", "URL to navigate to")
  .action(async (url) => {
    try {
      const result = await navigate(url);
      console.log(JSON.stringify(result, null, 2));
    } catch (error) {
      console.error("Error:", error);
    } finally {
      await closeBrowserSession();
    }
  });

program
  .command("screenshot")
  .description("Take a screenshot")
  .argument("[path]", "Path to save screenshot", "screenshot.png")
  .action(async (path) => {
    try {
      const result = await screenshot(path);
      console.log(JSON.stringify(result, null, 2));
    } catch (error) {
      console.error("Error:", error);
    } finally {
        await closeBrowserSession();
    }
  });

// Default to interactive mode if no args (process.argv only has node and script path)
if (process.argv.length <= 2) {
    process.argv.push("interactive");
}

program.parse();
