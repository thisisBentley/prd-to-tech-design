#!/usr/bin/env node
/**
 * Render the generated SVG swimlane diagrams to 1920×1080 PNG.
 *
 * Requires Playwright with a Chromium browser. Optional environment variables:
 * - PLAYWRIGHT_MODULE_ROOT: directory containing node_modules/playwright
 * - CHROME_HEADLESS_SHELL: explicit Chromium/headless-shell executable
 */
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const moduleRoot = process.env.PLAYWRIGHT_MODULE_ROOT;
const requirePlaywright = moduleRoot
  ? createRequire(path.join(moduleRoot, 'package.json'))
  : createRequire(import.meta.url);
const { chromium } = requirePlaywright('playwright');

const pairs = [
  ['docs/assets/agent-collaboration-swimlane.svg', 'docs/assets/agent-collaboration-swimlane.png'],
  ['docs/assets/agent-collaboration-swimlane-zh.svg', 'docs/assets/agent-collaboration-swimlane-zh.png'],
];

for (const [svg, png] of pairs) {
  const options = { headless: true, args: ['--no-sandbox', '--single-process'] };
  if (process.env.CHROME_HEADLESS_SHELL) options.executablePath = process.env.CHROME_HEADLESS_SHELL;
  const browser = await chromium.launch(options);
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.resolve(svg)).href, { waitUntil: 'load' });
  await page.screenshot({ path: path.resolve(png), fullPage: false });
  await page.close();
  await browser.close();
  console.log(png);
}
