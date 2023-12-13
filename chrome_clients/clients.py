import asyncio
import pyppeteer
import random
import re

from pyppeteer.browser import Browser
from pyppeteer.page import Page
from pyppeteer.element_handle import ElementHandle
from pyppeteer.us_keyboard_layout import keyDefinitions
from pyppeteer.errors import TimeoutError, ElementHandleError
from twocaptcha import TwoCaptcha

from typing import Union, List, Dict, Tuple


class RegistrationError(Exception):
    pass


class BasePuppeteerClient:
    def __init__(self, ws_url: str, logger=None):
        """
        Initializes the BasePuppeteerClient.

        :param ws_url: WebSocket URL for connecting to the Puppeteer browser.
        :param logger: Optional logger for logging messages.
        """
        self.ws_url = ws_url
        self.logger = logger
        self.browser: Union[Browser, None] = None
        self.page: Union[Page, None] = None
        self.error_handled = False

    async def __aenter__(self) -> "BasePuppeteerClient":
        """Enters the context, starting the Puppeteer browser."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Asynchronously starts the Puppeteer browser and sets the page."""
        self.browser = await pyppeteer.launcher.connect(browserWSEndpoint=self.ws_url)

        # Get the list of all open pages
        pages = await self.browser.pages()

        # Choose the page you want to work with (e.g., the first page in the list)
        if pages:
            self.page = pages[0]
        else:
            # If no pages are open, create a new one
            self.page = await self.browser.newPage()

    async def close(self):
        """Closes the Puppeteer browser."""
        if self.browser:
            # await asyncio.ensure_future(self.browser.close())
            await asyncio.ensure_future(self.browser.disconnect())

    @staticmethod
    def random_coordinates_within_box(
        x: float, y: float, width: float, height: float
    ) -> Tuple[float, float]:
        # Find the minimum and maximum x, y values within the box
        min_x, max_x = x, x + width
        min_y, max_y = y, y + height

        # Generate random x, y coordinates within the box
        random_x = random.uniform(min_x, max_x)
        random_y = random.uniform(min_y, max_y)

        return random_x, random_y

    @staticmethod
    async def sleep(lower: float, upper: float = None) -> None:
        if not upper:
            upper = lower

        total_sleep = random.uniform(lower, upper)

        await asyncio.sleep(total_sleep)

    async def is_present(self, selector: str, xpath: bool = False) -> bool:
        try:
            await self.find(selector, xpath, options={"visible": True, "timeout": 2000})

            return True
        except TimeoutError:
            return False

    async def find(
        self, selector: str, xpath: bool = False, options: Dict = None
    ) -> ElementHandle:
        if options is None:
            options = {"visible": True, "timeout": 5000}

        if xpath:
            return await self.page.waitForXPath(selector, options)
        else:
            return await self.page.waitForSelector(selector, options)

    async def find_all(self, selector: str, xpath: bool = False) -> List[ElementHandle]:
        options = {"visible": True, "timeout": 5000}

        if xpath:
            await self.page.waitForXPath(selector, options)
            return await self.page.xpath(selector)

        else:
            await self.page.waitForSelector(selector, options)
            return await self.page.querySelectorAll(selector)

    async def click(
        self, element: ElementHandle = None, selector: str = "", xpath: bool = False
    ) -> ElementHandle:
        if not element and selector:
            element = await self.find(selector, xpath)
        elif not element and not selector:
            raise ElementHandleError("No element or selector provided")

        # Scroll the element into view
        await element._scrollIntoViewIfNeeded()

        # Get the bounding box of the element
        bounding_box = await element.boundingBox()
        if bounding_box:
            x, y = self.random_coordinates_within_box(
                bounding_box["x"],
                bounding_box["y"],
                bounding_box["width"],
                bounding_box["height"],
            )
            # Perform the click at the chosen coordinates
            await self.page.mouse.click(x, y)
        else:
            await element.click()

        return element

    async def type(
        self, selector: str, text: str, xpath: bool = False, wpm: int = 100
    ) -> ElementHandle:
        # Check current text before proceeding
        element = await self.find(selector, xpath)
        current_text = await self.page.evaluate(
            "(element, text) => element.textContent.includes(text)",
            element,
            text,
        )

        self.logger.info(text)
        self.logger.info(current_text)
        if text == current_text:
            return element

        element = await self.click(selector=selector, xpath=xpath)

        # Calculate average pause between chars
        total_duration = len(text) / (wpm * 4.5)

        # Calculate time to wait between sending each character
        avg_pause = (total_duration * 60) / len(text)
        punctuation = [".", "!", "?", "\n"]

        words = 0
        last_char = ""
        for char in text:
            delay = random.uniform(avg_pause * 0.9, avg_pause * 1.2)

            if char in keyDefinitions:
                await self.page.keyboard.press(char)
            else:
                await self.page.keyboard.sendCharacter(char)

            if char == " ":
                words += 1

            if (
                char in punctuation
                and last_char not in punctuation
                and words > 3
                and random.random() < 0.1
            ):
                delay += random.uniform(0.2, 0.75)
                words = 0

            last_char = char
            await asyncio.sleep(delay)

        return element

    async def upload_file(
        self, selector: str, *file_paths: str, xpath: bool = False
    ) -> None:
        element = await self.find(selector, xpath)

        await element.uploadFile(*file_paths)

    async def click_random(
        self, selector: str, xpath: bool = False, count: int = None
    ) -> None:
        elements = await self.find_all(selector, xpath)

        if count is None:
            count = random.randint(int(len(elements) * 0.2), int(len(elements) * 0.65))

        selected_elements: List[ElementHandle] = random.choices(elements, k=count)

        for element in selected_elements:
            await self.click(element=element)

            await self.sleep(0.5, 0.84)


class PoshmarkClient(BasePuppeteerClient):
    async def _handle_form_errors(self) -> None:
        captcha_errors = [
            "Invalid captcha",
            "Please enter your login information and complete the captcha to continue.",
        ]
        error_classes = [".form__error-message", ".base_error_message", ".error_banner"]

        for error_class in error_classes:
            if await self.is_present(error_class):
                error_text = await self.page.querySelectorEval(
                    error_class, "(element) => element.textContent"
                )

                error_text = error_text.strip()

                if error_text in captcha_errors:
                    self.logger.info("Solving captcha...")
                    captcha_iframe = await self.find("iframe")
                    await captcha_iframe._scrollIntoViewIfNeeded()
                    captcha_src = await captcha_iframe.getProperty("src")
                    captcha_src_val = await captcha_src.jsonValue()

                    site_key = re.findall(r"(?<=k=)(.*?)(?=&)", captcha_src_val)[0]
                    solver = TwoCaptcha("c7e5b47cf69deba6946ef87b6d1faaf8")
                    result = solver.recaptcha(sitekey=site_key, url=self.page.url)

                    await self.page.evaluate(
                        f'grecaptcha.getResponse = () => "{result["code"]}"'
                    )
                    await self.page.evaluate("validateLoginCaptcha()")

                    self.logger.info("Captcha solved! Resubmitting form.")

                    await self.sleep(0.3, 1)

                    await self.click(selector="button[type='submit']")

                else:
                    raise RegistrationError(f"{error_class}: {error_text}")

    async def register(self, user_info: Dict) -> str:
        if "/signup" not in self.page.url:
            await self.page.goto("https://poshmark.com")
            await self.click(selector='a[href="/signup"]')

            await self.sleep(0.2, 0.9)

        target_username: str = user_info["username"]

        await self.type("#firstName", user_info["first_name"])
        await self.type("#lastName", user_info["last_name"])
        await self.type("#email", user_info["email"])
        await self.type('input[name="userName"]', target_username)
        await self.type("#password", user_info["password"])

        await self.sleep(0.2, 0.8)

        if user_info["gender"] is not None:
            await self.click(selector=".dropdown__selector--select-tag")

            await self.sleep(0.2, 0.8)

            await self.click(
                selector=f"//div[contains(@class, 'dropdown__link') and contains(text(), '{user_info['gender']}')]",
                xpath=True,
            )

        await self.click(selector='button[type="submit"]')

        retries = 0
        while retries < 3:
            await self._handle_form_errors()

            if await self.is_present('button[data-et-name="suggested_username"]'):
                await self.sleep(0.65, 1.25)

                target_username = await self.page.querySelectorEval(
                    'button[data-et-name="suggested_username"]',
                    "(element) => element.textContent",
                )

                target_username = target_username.strip()

                await self.click(selector='button[data-et-name="suggested_username"]')

                self.logger.info(f"New username selected: {target_username}")

            retries += 1

        return target_username

    async def finish_registration(self, profile_pic_path: str, zipcode: str) -> None:
        # Upload profile picture to .user-image
        await self.upload_file(".image-selector__input-img-files", profile_pic_path)

        await self.sleep(0.9, 1.5)
        await self.click(selector=".btn.btn--primary")
        await self.sleep(0.9, 1.5)

        # Set shirt/dress size
        await self.click(
            selector="//div[preceding-sibling::label[contains(text(), 'Shirt Size')]][@id='set-profile-info-size-dropdown']",
            xpath=True,
        )
        await self.click_random("ul.dropdown__menu--expanded > li", count=1)
        await self.sleep(0.9, 1.5)

        # Set shoe size
        await self.click(
            selector="//div[preceding-sibling::label[contains(text(), 'Shoe Size')]][@id='set-profile-info-size-dropdown']",
            xpath=True,
        )
        await self.click_random("ul.dropdown__menu--expanded > li", count=1)
        await self.sleep(0.9, 1.5)

        # Enter zipcode
        await self.type(selector='input[name="zip"]', text=zipcode)
        await self.sleep(0.9, 1.5)
        await self.click(selector='button[type="submit"]')
        await self.sleep(0.9, 1.5)

        # Select random number of brands
        await self.click_random(selector=".content-grid-item")
        await self.click(selector='button[type="submit"]')
        await self.sleep(0.9, 1.5)

        # Click submit again
        await self.click(selector='button[type="submit"]')
        await self.sleep(0.9, 1.5)

    async def login(self, username: str, password: str) -> None:
        if "/login" not in self.page.url:
            await self.page.goto("https://poshmark.com")
            await self.click(selector='a[href="/login"]')

            await self.sleep(0.2, 0.9)

        await self.type("#login_form_username_email", username)
        await self.type("#login_form_password", password)

        await self.sleep(0.2, 0.6)
        await self.click(selector='input[type="submit"]')

        retries = 0
        while retries < 3:
            await self._handle_form_errors()

    async def list_item(self, item: Dict) -> None:
        if "/feed" in self.page.url:
            await self.click(selector='a[href="/sell"]')
        elif "create-listing" in self.page.url:
            await self.page.reload()
        else:
            await self.page.goto("https://poshmark.com/")
            await self.click(selector='a[href="/sell"]')
