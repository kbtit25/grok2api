import time
import asyncio
import aiohttp

import re
import time,json

import secrets
import string
# from camoufox.async_api import AsyncCamoufox
# from browserforge.fingerprints import Screen

from patchright.async_api import async_playwright

import cum2
from dataclasses import dataclass
from typing import Optional

import emailclient as e1
import random

def random_string(length=16):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

async def block_images(route, request):
    url = route.request.url
    resource_type = route.request.resource_type

    if 'challenges.cloudflare.com/turnstile/v0/api.js' in url:
        await route.fulfill(path='./local-turnstile-api2.js')
        return

    allowed_types = {'document', 'script', 'xhr', 'fetch'}
    if resource_type in {'image', 'media', 'font'}:
        await route.abort()
        return

    elif resource_type in allowed_types:
        if 'google' in url or 'cloudflare' in url:
            print(f"Blocked: {url}")
            await route.abort()
            return
        await route.continue_()
        return

    await route.abort()
    return

async def extract_sso_cookie(context, interval=0.2, max_wait=5):
    """
    Repeatedly extracts cookies from the browser context every 'interval' seconds
    until the SSO cookie is detected. Saves its value to a file if found.
    Returns the cookie value if found, raises TimeoutError otherwise.
    
    Args:
        context: The browser context (e.g., from Playwright).
        interval (float): Time to wait between checks (seconds). Default: 0.2.
        max_wait (float): Maximum time to wait for SSO (seconds). Default: 30.
    """
    start_time = asyncio.get_event_loop().time()
    
    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > max_wait:
            raise TimeoutError(f"SSO cookie not found within {max_wait} seconds.")
        
        cookies = await context.cookies()
        sso_cookie = next((cookie for cookie in cookies if cookie['name'] == 'sso'), None)
        
        if sso_cookie:
            value = sso_cookie['value']
            print("SSO cookie value:", value)
            
            # Async-safe file append
            def append_to_file():
                with open("sso_cookies.txt", "a") as f:
                    f.write(value + "\n")
            
            await asyncio.to_thread(append_to_file)
            
            print(f"SSO detected after {elapsed:.1f} seconds.")
            return value
        
        await asyncio.sleep(interval)

async def main2():
    async with async_playwright() as p:
        # browser = await p.firefox.launch(headless=False)
        browser = await p.chromium.launch(
            # proxy={
            #     "server": 'http://89.117.94.75:300'+str(random.randint(10,99)),
            #     "username": 'x',
            #     "password": 'fake password/'
            # },
            # proxy={
            #     "server": 'http://192.168.68.127:8080',
            #     "username": None,
            #     "password": None
            # },

            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--start-minimized',
                '--disable-software-rasterizer',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                
                '--disable-background-networking',
                '--disable-sync',
                '--disable-web-security',
                '--disable-blink-features=AutomationControlled',
            ],
            channel="chrome",  # ensure it uses your local Chrome
        )
    # constrains = Screen(max_width=1920, max_height=1080) 
    # async with AsyncCamoufox(
    #     screen=constrains,
    #     webgl_config=("Apple", "Apple M1, or similar"),
    #     os="macos",
    # ) as browser:

        context = await browser.new_context(
            timezone_id="America/New_York",
            locale="en-US",  # may still be ignored on Windows, but combined with --lang it works
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )


        await context.route('**/*', block_images)

        page = await context.new_page()
        await page.set_viewport_size({"width": 500, "height": 500})



        await page.goto("https://accounts.x.ai/sign-up")
        
        await page.add_init_script("""
          (function() {
            const originalAttachShadow = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
              const shadow = originalAttachShadow.call(this, init);
              if (init.mode === 'closed') {
                window.__lastClosedShadowRoot = shadow;
              }
              return shadow;
            };
          })();
        """)


        await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
        };
        """)
        emclient = e1.EmailClient()
        e = await emclient.get_email()

        await page.get_by_role("button", name="Sign up with email").wait_for(state="visible")
        await page.get_by_role("button", name="Sign up with email").click()

        # Fill the email input
        email_input = await page.wait_for_selector('[data-testid="email"]')
        await email_input.fill(e)

        await page.get_by_role("button", name="Sign up").wait_for()
        await page.get_by_role("button", name="Sign up").click()

        otp_input = await page.wait_for_selector('input[data-input-otp="true"]')
        code_email = await emclient.get_code(timeout=30)
        print(code_email,"df")
        await emclient.close()
        await otp_input.type(code_email, delay=1)  # delay in ms between keystrokes

        first_name_input = page.locator('input[data-testid="givenName"]')
        # Wait until the element is visible
        await first_name_input.wait_for(state="visible")
        await first_name_input.type("Erika")

        first_name_input = page.locator('input[data-testid="familyName"]')
        # Wait until the element is visible
        await first_name_input.wait_for(state="visible")
        await first_name_input.type("Kirk")

        
        d2dd = page.locator('input[name="password"]')
        await d2dd.wait_for(state="visible")
        await d2dd.type("vwervdd22rfeDgFJFJ8")
        
        solver = cum2.AsyncTurnstileSolver(headless=False, browser_type="chrome")
        result = await solver.solve(
            url="https://accounts.x.ai/sign-in",
            sitekey="0x4AAAAAAAhr9JGVDZbrZOo0",
        )
        token = result.token
        
        result = await page.evaluate(f"""
            () => {{
            const widget = document.querySelector('[data-turnstile-widget="active"]');
            if (!widget) return false;
            
            // Add the token input - this should trigger the observer
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'cf-turnstile-response';
            input.value = '{token}';
            widget.appendChild(input);
            
            // Also set as attribute (backup trigger)
            widget.setAttribute('data-token', '{token}');
            widget.setAttribute('data-solved', 'true');
            
            // Update visual appearance
            const mockDiv = widget.querySelector('.cf-turnstile');
            if (mockDiv) {{
                mockDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: green;">✓ Verified</div>';
                mockDiv.style.backgroundColor = '#e8f5e8';
            }}
            
            console.log('Token input added, observer should trigger callback');
            return true;
        }}
        """)
        print(result)
        
        await page.get_by_role("button", name="Complete sign up").wait_for(state="visible")
        await page.get_by_role("button", name="Complete sign up").click()
        # await page.wait_for_load_state("networkidle")

        # page.goto("https://accounts.x.ai/account")

        await extract_sso_cookie(context, max_wait=3)
        
async def main_loop():
    while True:
        try:
            try:
                await asyncio.wait_for(main2(), timeout=88)  
            except:
                pass
        except asyncio.TimeoutError:
            print("Task timed out, retrying...")

if __name__ == "__main__":
    asyncio.run(main_loop())
