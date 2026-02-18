import { getBrowserSession } from "./session.js";
import { Page } from "playwright";

export async function navigate(url: string) {
  const { page } = await getBrowserSession();
  if (!page) throw new Error("No browser session");
  await page.goto(url);
  return { url: page.url(), title: await page.title() };
}

export async function screenshot(path: string = "screenshot.png") {
  const { page } = await getBrowserSession();
  if (!page) throw new Error("No browser session");
  await page.screenshot({ path, fullPage: true });
  return { path };
}

export async function click(selector: string) {
  const { page } = await getBrowserSession();
  if (!page) throw new Error("No browser session");
  await page.click(selector);
  return { success: true };
}

export async function type(selector: string, text: string) {
    const { page } = await getBrowserSession();
    if (!page) throw new Error("No browser session");
    await page.fill(selector, text);
    return { success: true };
}

export async function getText(selector: string) {
    const { page } = await getBrowserSession();
    if (!page) throw new Error("No browser session");
    return await page.textContent(selector);
}

export async function getHtml(selector?: string) {
    const { page } = await getBrowserSession();
    if (!page) throw new Error("No browser session");
    if(selector) {
        return await page.innerHTML(selector);
    }
    return await page.content();
}
