# biggest anime jihadi in the world!
import time
import asyncio
import aiohttp
import random

import re
import time,json

import secrets
import string

from browserforge.fingerprints import Screen

from patchright.async_api import async_playwright

from dataclasses import dataclass
from typing import Optional


def random_string(length=16):
    alphabet = string.ascii_letters + string.digits

    return ''.join(secrets.choice(alphabet) for _ in range(length))



@dataclass
class TurnstileResult:
    token: Optional[str] = None
    elapsed_time_seconds: float = 0.0
    status: str = "failure"
    reason: Optional[str] = None


class TurnstilePage:
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Turnstile Solver</title>
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=jt22s3lxf0a" async></script>
    </head>
    <body>
        <div id="cf-container"></div>
        <script>
            const interval = setInterval(() => {{
                if (window.turnstile) {{
                    clearInterval(interval);
                    window.turnstile.render('#cf-container', {{
                        sitekey: "{sitekey}",
                        theme: "light",
                        size: "flexible"
                    }});
                }}
            }}, 100);
        </script>
    </body>
    </html>
    """



    def __init__(self, page, url: str, sitekey: str):
        self.page = page
        self.url = url if url.endswith("/") else url + "/"
        self.sitekey = sitekey

    async def _optimized_route_handler(self, route):
        """Оптимизированный обработчик маршрутов для экономии ресурсов."""
        url = route.request.url
        resource_type = route.request.resource_type

        allowed_types = {'document', 'script', 'xhr', 'fetch'}

        allowed_domains = [
            'challenges.cloudflare.com',
            'static.cloudflareinsights.com',
            'cloudflare.com'
        ]
        # headers = route.request.headers.copy()
        # print(headers)
        # headers["sec-ch-ua"] = '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"'
        # headers["sec-ch-ua-mobile"] = "?0"
        # headers["sec-ch-ua-platform"] = '"Windows"'
        

        # if "cloudflareinsights.com" in url: 
        #     await route.abort()
        if resource_type in allowed_types:
            await route.continue_()
        elif any(domain in url for domain in allowed_domains):
            await route.continue_() 
        else:
            await route.abort()
    
    async def setup(self):
        html_content = self.HTML_TEMPLATE.format(sitekey=self.sitekey)
        await self.page.route(self.url, lambda route: route.fulfill(body=html_content, status=200))
        
        await self.page.add_init_script("""
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

        # await self.page.add_init_script("""
        #     Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        #     Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        #     """)
        # await self.page.set_viewport_size({"width": random.randint(1200, 1920),
        #                       "height": random.randint(700, 1080)})
        # await self.page.mouse.move(130, 100)

        await self.page.route("**/*", self._optimized_route_handler)
        await self.page.goto(self.url, wait_until='domcontentloaded', timeout=30000)
        await self.page.unroute("**/*", self._optimized_route_handler)


    async def get_token(self, max_attempts: int = 10) -> Optional[str]:
        await asyncio.sleep(0.2)#weird bug fix?
        # await self.page.get_by_role("button", name="Login with email").wait_for(state="visible")
        await self.page.get_by_role("button", name="Login with email").click()
        # button = await self.page.wait_for_selector('button:has-text("Login with email")', state="visible")
        # button.click()



        # await self.page.waitForSelector('button:has-text("Login with email")')
        # await self.page.click('button:has-text("Login with email")')

        
        first_name_input = self.page.locator('input[data-testid="email"]')
        await first_name_input.wait_for(state="visible")
        await first_name_input.type("ffefkef@gmail.com")

        await self.page.get_by_role("button", name="Next").click()

        for _ in range(max_attempts):
            try:
                token = await self.page.input_value("[name=cf-turnstile-response]")
                if token:
                    return token

                iframe_element = await self.page.wait_for_selector("iframe[id^='cf-chl-widget-']", timeout=5000)
                frame = await iframe_element.content_frame()
                if frame:
                    checkbox = frame.locator("input[type='checkbox']")
                    await checkbox.click(timeout=3000)
                    for _ in range(20):
                        token = await self.page.input_value("[name=cf-turnstile-response]")
                        if token:
                            return token
                        await asyncio.sleep(0.5)
            except Exception:
                await asyncio.sleep(1)
        return None


class AsyncTurnstileSolver:
    def __init__(self, headless: bool = True, useragent: Optional[str] = None, browser_type: str = "msedge"):
        self.headless = headless
        self.useragent = useragent
        self.browser_type = browser_type
        self.browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                # '--disable-gpu',
                # "--lang=en-US",
            
            ]

    async def solve(self, url: str, sitekey: str) -> TurnstileResult:
        start_time = time.time()
        result = TurnstileResult()
        playwright = None
        browser = None

        try:
            if self.browser_type in ["chromium", "chrome", "msedge"]:
                playwright = await async_playwright().start()
                # browser = await playwright.chromium.launch_persistent_context(
                        # user_data_dir="./userdata",
                browser = await playwright.chromium.launch(
                    # proxy={
                    #     "server": 'http://89.117.94.75:'+str(random.randint(30001,30188)),
                    #     "'
                    # },
            headless=self.headless, args=self.browser_args,channel=self.browser_type)
            elif self.browser_type == "camoufox":
                browser = await AsyncCamoufox(headless=False).start()
            else:
                result.reason = f"Unsupported browser type: {self.browser_type}"
                return result

            # context = await browser.new_context()
            # context = await browser.new_context(
            #     # timezone_id="America/New_York",
            #     # locale="en-US",  # may still be ignored on Windows, but combined with --lang it works
            #     # extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            # )
            page = await browser.new_page()
            tp = TurnstilePage(page, url, sitekey)
            await tp.setup()
            token = await asyncio.wait_for(tp.get_token(), timeout=30)

            
            
            result.elapsed_time_seconds = round(time.time() - start_time, 3)
            if token:
                result.token = token
                result.status = "success"
            else:
                result.reason = "Max attempts reached without token retrieval"

        except Exception as e:
            result.reason = str(e)

        finally:
            if browser is not None:
                try:
                    await browser.close()
                except:
                    pass
            if playwright is not None and self.browser_type in ["chromium", "chrome","msedge"]:
                try:
                    await playwright.stop()
                except:
                    pass

        return result

# from browserforge.fingerprints import Screen

async def main2():
    solver = AsyncTurnstileSolver(headless=False, browser_type="chrome")
    result = await solver.solve(
        url="https://accounts.x.ai/sign-in",
        sitekey="0x4AAAAAAAhr9JGVDZbrZOo0",
    )
    print(result)

    async with async_playwright() as p:
        # browser = await p.firefox.launch(headless=False)
        browser = await p.chromium.launch(
            # proxy={
            #     "server": 'http://89.117.94.75:30099',
            # },
            # proxy={
            #     "server": 'http://192.168.68.127:8080',
            #     "username": None,
            #     "password": None
            # },
            headless=False,
            channel="msedge",  # ensure it uses your local Chrome
        )
        async def handle_route(route):
            await route.fulfill(path='./local-turnstile-api2.js')


        


        # Create context with timezone and extra headers
        context = await browser.new_context(
            timezone_id="America/New_York",
            locale="en-US",  # may still be ignored on Windows, but combined with --lang it works
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            no_viewport=True
        )
        await context.route('**/challenges.cloudflare.com/turnstile/v0/api.js*', handle_route)


        async def handle_route(route):
            await route.fulfill(path='./local-turnstile-api2.js')

        # await context.route('**/challenges.cloudflare.com/turnstile/v0/api.js*', handle_route)

        page = await context.new_page()
        await page.set_viewport_size({"width": 500, "height": 500})



        await page.goto("https://accounts.x.ai/sign-in")
        
        await page.get_by_role("button", name="Login with email").wait_for(state="visible")
        await page.get_by_role("button", name="Login with email").click()

        
        first_name_input = page.locator('input[data-testid="email"]')
        # Wait until the element is visible
        await first_name_input.wait_for(state="visible")
        await first_name_input.type("ffefkef@gmail.com")

        await page.get_by_role("button", name="Next").click()

        d2dd = page.locator('input[name="password"]')
        await d2dd.wait_for(state="visible")
        await d2dd.type("vwervegerg")
        
        solver = AsyncTurnstileSolver(headless=False, browser_type="chrome")
        result = await solver.solve(
            url="https://accounts.x.ai/sign-in",
            sitekey="0x4AAAAAAAhr9JGVDZbrZOo0",
        )
        print(result)
        token = result.token
        # token = ""
        #### saves pn deadbeat memory bendwidth
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
        print("can click")

        await page.get_by_role("button", name="Login").wait_for(state="visible")
        await page.get_by_role("button", name="Login").click()


# # Run the async main
if __name__ == "__main__":
    asyncio.run(main2())
