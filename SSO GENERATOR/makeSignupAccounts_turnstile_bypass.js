  import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { connect } from 'puppeteer-real-browser';
import { EmailClient } from './emailclient.mjs';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// --- CACHING LOGIC (Unchanged) ---
const cacheDir = path.resolve('./cache');
if (!fs.existsSync(cacheDir)) fs.mkdirSync(cacheDir);

function sanitize(str) {
  return str.replace(/[<>:"|?*]/g, '_');
}

function getCachePath(url) {
  try {
    const urlObj = new URL(url);
    if (!['http:', 'https:'].includes(urlObj.protocol)) return null;

    const hostname = sanitize(urlObj.hostname);
    if (!hostname) return null;

    let pathname = decodeURIComponent(urlObj.pathname);
    if (pathname === '/' || pathname.endsWith('/')) {
      pathname = path.join(pathname, 'index.html');
    }

    const fileDir = path.dirname(pathname);
    let fileName = path.basename(pathname);
    fileName = sanitize(fileName);

    if (urlObj.search) {
      const queryHash = crypto.createHash('md5').update(urlObj.search).digest('hex').substring(0, 8);
      const ext = path.extname(fileName);
      const base = path.basename(fileName, ext);
      const safeBase = base.length > 100 ? base.substring(0, 100) : base;
      fileName = `${safeBase}_${queryHash}${ext}`;
    }

    const fullDir = path.join(cacheDir, hostname, fileDir);
    const baseFilePath = path.join(fullDir, fileName);

    return {
      bodyFile: `${baseFilePath}.body`,
      metaFile: `${baseFilePath}.meta`,
      directory: fullDir,
    };
  } catch (error) {
    console.warn(`Could not create cache path for URL: ${url}`);
    return null;
  }
}

// --- HELPER FUNCTIONS (Unchanged) ---
function isIgnoredUrl(url) {
  return url.includes('challenges.cloudflare.com') || url.includes('turnstile');
}

async function extractSsoCookie(page, interval = 200, maxWait = 5000) {
  const start = Date.now();
  while (Date.now() - start < maxWait) {
    const cookies = await page.cookies().catch(() => []);
    const sso = cookies.find(c => c && c.name === 'sso');
    if (sso) {
      const value = sso.value;
      await fs.promises.appendFile('sso_cookies.txt', `${value}\n`);
      console.log('SSO cookie value:', value);
      return value;
    }
    await sleep(interval);
  }
  // This is not a critical error, so we just warn instead of throwing.
  console.warn('SSO cookie not found within the time limit.');
}

async function waitForCaptcha(page, timeout = 33000, interval = 1000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const token = await page.evaluate(() => {
      const el = document.querySelector('[name="cf-turnstile-response"]');
      return el?.value?.length > 20 ? el.value : null;
    });
    if (token) {
      console.log("✅ Captcha solved:", token);
      return token;
    }
    await sleep(interval);
  }
  console.log("⚠️ Captcha not solved within", timeout / 1000, "seconds");
  return null;
}

// --- PROXY CONFIG (Unchanged) ---
const PROXY_USER = '1';
const PROXY_PASS = '1';
const PROXY_HOST = 'fr.decodo.com';
const PROXY_PORT = 40033;


async function runSignup(context, instanceId) {
  let totalBytesSent = 0;
  let totalBytesReceived = 0;
  const page = await context.newPage();

  try {
    // --- Page Setup ---
    await page.setExtraHTTPHeaders({
      'Accept-Language': 'zh-CN,en;q=0.9,en;q=0.8',
    });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36');

    // --- Request Interception and Caching ---
    await page.setRequestInterception(true);
    page.on('request', req => {
        const url = req.url();
        if (isIgnoredUrl(url) || req.method() !== 'GET') {
            return req.continue();
        }
        const cachePaths = getCachePath(url);
        if (cachePaths && fs.existsSync(cachePaths.bodyFile) && fs.existsSync(cachePaths.metaFile)) {
            try {
                const body = fs.readFileSync(cachePaths.bodyFile);
                const meta = JSON.parse(fs.readFileSync(cachePaths.metaFile, 'utf8'));
                return req.respond({ status: 200, headers: meta, body });
            } catch (e) {
                console.warn(`[Instance ${instanceId}][Cache Read Error] ${e.message}`);
            }
        }
        req.continue();
    });

    page.on('requestfinished', req => {
      const postData = req.postData();
      if (postData) totalBytesSent += Buffer.byteLength(postData, 'utf8');
    });

    page.on('response', async res => {
        const url = res.url();
        if (res.request().method() !== 'GET' || res.fromCache() || res.status() !== 200 || isIgnoredUrl(url)) {
            return;
        }
        try {
            const buffer = await res.buffer();
            if (buffer.length === 0) return;
            totalBytesReceived += buffer.length;
            const cachePaths = getCachePath(url);
            if (cachePaths && !fs.existsSync(cachePaths.bodyFile)) {
                const headers = { 'content-type': res.headers()['content-type'] || 'application/octet-stream' };
                fs.mkdirSync(cachePaths.directory, { recursive: true });
                fs.writeFileSync(cachePaths.bodyFile, buffer);
                fs.writeFileSync(cachePaths.metaFile, JSON.stringify(headers));
            }
        } catch (e) { /* ignore errors */ }
    });

    // --- Automation Logic ---
    const emclient = new EmailClient();
    try {
      const email = await emclient.getEmail();
      await page.goto('https://accounts.x.ai/sign-up', { waitUntil: 'networkidle2', timeout: 60000 });

      const signUpEmailButtonSelector = 'button ::-p-text(Sign up with email)';
      await page.waitForSelector(signUpEmailButtonSelector, { timeout: 10000 });
      await page.click(signUpEmailButtonSelector);

      const emailInputSelector = '[data-testid="email"]';
      await page.waitForSelector(emailInputSelector, { visible: true });
      await page.type(emailInputSelector, email, { delay: 20 });
      
      const signUpButtonSelector = 'button ::-p-text(Sign up)';
      await page.waitForSelector(signUpButtonSelector);
      await page.click(signUpButtonSelector);

      const otpInputSelector = 'input[data-input-otp="true"]';
      await page.waitForSelector(otpInputSelector, { visible: true, timeout: 45000 });
      const code = await emclient.getCode();
      console.log(`Instance ${instanceId}: Received OTP code:`, code);
      await page.type(otpInputSelector, code, { delay: 25 });

      await page.waitForSelector('input[data-testid="givenName"]', { visible: true, timeout: 45000 });
      await page.type('[data-testid="givenName"]', 'Erika', { delay: 20 });
      await page.type('[data-testid="familyName"]', 'Kirk', { delay: 22 });
      await page.type('input[name="password"]', 'vwervdd22rfeDgFJFJ8', { delay: 21 });

      await waitForCaptcha(page, 33000);

      const completeButtonSelector = 'button ::-p-text(Complete sign up)';
      await page.waitForSelector(completeButtonSelector);
      await page.click(completeButtonSelector);

      await extractSsoCookie(page, 300, 8000);

    } catch (error) {
        console.error(`[Instance ${instanceId}] Error during signup automation: ${error.message}`);
        // Re-throw the error to ensure the worker catches it and restarts.
        throw error;
    } finally {
        await emclient.close().catch(() => {});
    }
  } finally {
    console.log(`Instance ${instanceId} network usage: Sent ${totalBytesSent} bytes, Received ${totalBytesReceived} bytes`);
    await page.close().catch(() => {});
  }
}

/**
 * A worker that uses a shared browser instance to run sign-up processes
 * in isolated contexts in an infinite loop.
 * @param {import('puppeteer').Browser} browser The shared browser instance.
 * @param {number} instanceId The ID for this worker instance.
 */
async function signupWorker(browser, instanceId) {
  while (true) {
    let context = null;
    try {
      console.log(`[Worker ${instanceId}] Starting new signup process...`);
      // The correct, modern method for creating an isolated context.
      context = await browser.createBrowserContext();
      await runSignup(context, instanceId);
      console.log(`[Worker ${instanceId}] Signup process finished. Restarting...`);
    } catch (error) {
      console.error(`[Worker ${instanceId}] An error occurred: ${error.message}. Restarting the process...`);
      await sleep(5000);
    } finally {
      if (context) {
        await context.close();
      }
    }
  }
}

/**
 * Main function: launches a single browser and starts multiple concurrent workers.
 */
async function main() {
  let browser = null;
  try {
    const { browser: connectedBrowser } = await connect({
      headless: false,
      turnstile: true,
      disableXvfb: true,
      customConfig: { chromePath: `C:\\Users\\User\\AppData\\Local\\Chromium\\Application\\chrome.exe` },
      args: [
        "--start-maximized", '--lang=fr-FR', "--disable-v8-idle-tasks", "--disable-webgl-image-chromium",
        "--disable-3d-apis", "--canvas-2d-layers", "--disable-accelerated-video-decode",
        "--disable-accelerated-video-encode", "--disable-backing-store-limit", "--disable-remote-fonts",
        "--disable-shared-workers", "--disable-skia-runtime-opts", "--disable-smooth-scrolling",
        "--disable-software-rasterizer", "--disable-speech-api", "--disable-speech-synthesis-api",
        "--no-sandbox", "--no-zygote", "--disable-yuv-image-decoding", "--disable-notifications",
        "--javascript-harmony", "--private-aggregation-developer-mode",
      ],
      connectOption: { defaultViewport: null },
      // proxy: { host: PROXY_HOST, port: PROXY_PORT, username: PROXY_USER, password: PROXY_PASS },
    });
    browser = connectedBrowser;

    const instances = 5;
    console.log(`Starting ${instances} concurrent signup workers...`);

    const workerPromises = [];
    for (let i = 0; i < instances; i++) {
      workerPromises.push(signupWorker(browser, i + 1));
    }
    await Promise.all(workerPromises);

  } catch (err) {
    console.error('Fatal error in main execution:', err);
  } finally {
    if (browser) {
      await browser.close();
    }
    process.exit(1);
  }
}

main();