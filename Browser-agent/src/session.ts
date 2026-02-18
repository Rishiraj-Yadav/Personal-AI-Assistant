import { chromium, firefox, webkit, Browser, BrowserContext, Page } from "playwright";
import { config } from "./config.js";

type BrowserInstance = {
  browser?: Browser;
  context?: BrowserContext;
  page?: Page;
};

let instance: BrowserInstance = {};

export async function getBrowserSession() {
  if (instance.page) return instance;

  const launchOptions = {
    headless: config.HEADLESS,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
    proxy: config.PROXY_SERVER ? { server: config.PROXY_SERVER } : undefined,
  };

  if (config.BROWSER_TYPE === "firefox") {
    instance.browser = await firefox.launch(launchOptions);
  } else if (config.BROWSER_TYPE === "webkit") {
    instance.browser = await webkit.launch(launchOptions);
  } else {
    instance.browser = await chromium.launch(launchOptions);
  }

  instance.context = await instance.browser.newContext();
  instance.page = await instance.context.newPage();

  return instance;
}

export async function closeBrowserSession() {
  if (instance.browser) {
    await instance.browser.close();
    instance = {};
  }
}
