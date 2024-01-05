import asyncio
import os
import pyppeteer
import random
import re
import requests

from pyppeteer.browser import Browser
from pyppeteer.page import Page
from pyppeteer.element_handle import ElementHandle
from pyppeteer.us_keyboard_layout import keyDefinitions
from pyppeteer.errors import TimeoutError, ElementHandleError
from twocaptcha import TwoCaptcha
from urllib.parse import urlparse, parse_qs

from typing import Union, List, Dict, Tuple, Callable
from .errors import *


class OctoAPIClient:
    def __init__(self):
        self.octo_api = "https://app.octobrowser.net/api/v2/automation"
        self.octo_local_api = (
            f"http://{os.environ.get('OCTO_ENDPOINT', '127.0.0.1')}:58888/api"
        )

        self._octo_api_headers = {
            "X-Octo-Api-Token": os.environ["OCTO_API_KEY"],
            "Content-Type": "application/json",
        }
        self._octo_local_api_header = {"Content-Type": "application/json"}

    def check_username(self) -> Dict:
        response = requests.get(
            f"{self.octo_local_api}/username", headers=self._octo_local_api_header
        )
        json_response = response.json()

        if "error" in json_response:
            raise NotLoggedInError(response.text)

        return json_response

    def get_profile(self, uuid: str) -> Dict:
        response = requests.get(
            f"{self.octo_api}/profiles/{uuid}", headers=self._octo_api_headers
        )
        json_response = response.json()

        return json_response["data"]

    def get_profiles(
        self, search: str = None, fields: List[str] = None, ordering: str = "-created"
    ) -> Dict:
        if fields is None:
            fields = ["title", "description", "proxy", "tags", "status"]

        params = {"fields": ",".join(fields), "ordering": ordering}

        if search is not None:
            params["search"] = search

        response = requests.get(
            f"{self.octo_api}/profiles", headers=self._octo_api_headers, params=params
        )

        return response.json()

    def create_profile(
        self,
        title: str,
        tags: List[str] = None,
        fingerprint: Dict = None,
        proxy_uuid: str = None,
    ) -> str:
        if fingerprint is None:
            fingerprint = {"dns": "8.8.8.8", "os": "win"}

        data = {"title": title, "fingerprint": fingerprint}

        if proxy_uuid is not None:
            data["proxy"] = {"uuid": proxy_uuid}

        if tags is not None:
            existing_tags = self.get_tags()
            existing_tags = [existing_tag["name"] for existing_tag in existing_tags]

            for tag in tags:
                if tag not in existing_tags:
                    self.create_tag(tag)

            data["tags"] = tags

        response = requests.post(
            f"{self.octo_api}/profiles", headers=self._octo_api_headers, json=data
        )
        json_response = response.json()

        return json_response["data"]["uuid"]

    def get_tags(self) -> List:
        response = requests.get(f"{self.octo_api}/tags", headers=self._octo_api_headers)
        json_response = response.json()

        return json_response["data"]

    def create_tag(self, tag_name: str) -> None:
        response = requests.post(
            f"{self.octo_api}/tags",
            headers=self._octo_api_headers,
            json={"name": tag_name},
        )
        json_response = response.json()

        return json_response["data"]["uuid"]

    def update_profile(
        self,
        uuid: str,
        title: str = None,
        tags: List[str] = None,
        fingerprint: Dict = None,
        proxy_uuid: str = None,
    ) -> Dict:
        data = {}

        if title is not None:
            data["title"] = title

        if tags is not None:
            data["tags"] = tags

        if fingerprint is not None:
            data["fingerprint"] = fingerprint

        if proxy_uuid is not None:
            data["proxy"] = {"uuid": proxy_uuid}
        else:
            data["proxy"] = None

        response = requests.patch(
            f"{self.octo_api}/profiles/{uuid}",
            headers=self._octo_api_headers,
            json=data,
        )
        json_response = response.json()

        return json_response["data"]

    def get_proxies(self, external_id: str = None) -> List[Dict]:
        response = requests.get(
            f"{self.octo_api}/proxies", headers=self._octo_api_headers
        )
        json_response = response.json()

        if external_id is None:
            return json_response["data"]

        for proxy in json_response["data"]:
            if proxy["external_id"] == external_id:
                return [proxy]

    def create_proxy(self, data: Dict) -> Dict:
        response = requests.post(
            f"{self.octo_api}/proxies", json=data, headers=self._octo_api_headers
        )

        return response.json()["data"]

    def update_proxy(self, proxy_uuid: str, data: Dict):
        response = requests.patch(
            f"{self.octo_api}/proxies/{proxy_uuid}",
            json=data,
            headers=self._octo_api_headers,
        )

        return response.json()["data"]

    def get_active_profiles(self):
        active_profiles = requests.get(
            f"{self.octo_local_api}/profiles/active",
            headers=self._octo_local_api_header,
        ).json()

        return active_profiles

    def start_profile(self, uuid: str) -> Dict:
        data = {
            "uuid": uuid,
            "headless": False,
            "debug_port": True,
            "flags": ["--disable-backgrounding-occluded-windows"],
        }

        response = requests.post(
            f"{self.octo_local_api}/profiles/start",
            headers=self._octo_local_api_header,
            json=data,
        )
        json_response = response.json()

        if "error" in json_response:
            raise ProfileStartError(f'{json_response["error"]},{uuid}')

        return json_response

    def stop_profile(self, uuid: str) -> Dict:
        data = {"uuid": uuid}

        response = requests.post(
            f"{self.octo_local_api}/profiles/stop/",
            headers=self._octo_local_api_header,
            json=data,
        )
        json_response = response.json()

        return json_response

    def force_stop_profile(self, uuid: str) -> Dict:
        data = {"uuid": uuid}
        response = requests.post(
            f"{self.octo_local_api}/profiles/force_stop",
            headers=self._octo_local_api_header,
            json=data,
        )
        json_response = response.json()

        return json_response

    def delete_profiles(self, uuids: List[str]) -> Dict:
        data = {"uuids": uuids, "skip_trash_bin": True}
        response = requests.delete(
            f"{self.octo_api}/profiles", headers=self._octo_api_headers, json=data
        )
        json_response = response.json()

        return json_response


class BasePuppeteerClient:
    def __init__(self, ws_url: str, width: int = 800, height: int = 600, logger=None):
        """
        Initializes the BasePuppeteerClient.

        :param ws_url: WebSocket URL for connecting to the Puppeteer browser.
        :param width: The width of the viewport for the Puppeteer browser.
        :param height: The height of the viewport for the Puppeteer browser.
        :param logger: Optional logger for logging messages.
        """
        self.ws_url = ws_url
        self.width = width
        self.height = height
        self.logger = logger
        self.browser: Union[Browser, None] = None
        self.page: Union[Page, None] = None
        self.recovery_attempted = False

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

        self.page.setDefaultNavigationTimeout(60000)
        await self.page.setViewport(
            {"width": self.width, "height": self.height, "deviceScaleFactor": 1}
        )

    async def close(self):
        """Disconnects from the debug session."""
        if self.browser:
            await self.browser.close()

    @staticmethod
    def cleanse_selector(selector):
        """
        Cleanses a string to be used as a CSS selector by removing characters
        that are not valid in CSS identifiers.

        This function keeps letters (a-z, A-Z), digits (0-9), hyphens (-),
        and underscores (_), and removes all other characters. It does not handle
        cases where the selector starts with a digit or two hyphens, which are
        technically invalid in CSS.

        Parameters:
        selector (str): The string to be cleansed for use as a CSS selector.

        Returns:
        str: A cleansed string with only valid CSS identifier characters.
        """
        return re.sub(r"[^a-zA-Z0-9-_]", "", selector)

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

    async def save_screenshot(self, directory: str, filename: str) -> None:
        screenshots_dir = os.path.join(os.getcwd(), directory)
        screenshot_path = os.path.join(screenshots_dir, filename)
        try:
            os.makedirs(screenshots_dir, exist_ok=True)
            await self.page.screenshot({"path": screenshot_path})
            self.logger.info(f"Screenshot saved to {screenshot_path}")
        except Exception:
            self.logger.warning(f"Could not save screenshot to {screenshot_path}")

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
        self,
        element: ElementHandle = None,
        selector: str = "",
        xpath: bool = False,
        navigation: bool = False,
        navigation_options: Dict = None,
    ) -> ElementHandle:
        if navigation and navigation_options is None:
            navigation_options = {"timeout": 30000}
        if not element and selector:
            element = await self.find(selector, xpath)
        elif not element and not selector:
            raise ElementHandleError("No element or selector provided")

        # Scroll the element into view
        try:
            await asyncio.wait_for(element._scrollIntoViewIfNeeded(), 4)
        except asyncio.TimeoutError:
            self.logger.info("Timeout waiting for scroll into view")

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
            if navigation:
                completed, _ = await asyncio.wait(
                    [
                        self.page.mouse.click(x, y),
                        self.page.waitForNavigation(navigation_options),
                    ],
                )

                for task in completed:
                    if task.exception():
                        if isinstance(task.exception(), TimeoutError):
                            self.logger.warning(
                                "Timed out waiting for navigation after click"
                            )

            else:
                await self.page.mouse.click(x, y)
        else:
            if navigation:
                completed, _ = await asyncio.wait(
                    [
                        element.click(),
                        self.page.waitForNavigation(navigation_options),
                    ],
                )

                for task in completed:
                    if task.exception():
                        if isinstance(task.exception(), TimeoutError):
                            self.logger.warning(
                                "Timed out waiting for navigation after click"
                            )
            else:
                await element.click()

        return element

    async def type(
        self, selector: str, text: str, xpath: bool = False, wpm: int = 100
    ) -> ElementHandle:
        # Check current text before proceeding
        element = await self.find(selector, xpath)
        current_text = await self.page.evaluate(
            "(element) => element.textContent", element
        )

        if text == current_text:
            return element
        elif current_text != "":
            for _ in current_text:
                await self.page.keyboard.press("Backspace")

        element = await self.click(selector=selector, xpath=xpath)

        # Calculate average pause between chars
        total_duration = len(text) / (wpm * 4.5)

        # Calculate time to wait between sending each character
        avg_pause = (total_duration * 60) / len(text)
        punctuation = [".", "!", "?"]

        words = 0
        last_char = ""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            for char in line:
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
            if index != len(lines) - 1:
                await self.page.keyboard.press("Enter")
                if random.random() < 0.1:
                    random.uniform(0.2, 0.75)

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

    async def check_fingerprint(self):
        await self.page.goto("https://iphey.com/")
        await self.sleep(10)

        await self.save_screenshot("screenshots", "fingerprint_check.png")

        title_text = await self.page.querySelectorEval(
            ".fw-500", "(element) => element.textContent"
        )

        self.logger.info(f"-------->{title_text}<--------")


class PoshmarkClient(BasePuppeteerClient):
    async def _handle_form_errors(self) -> bool:
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
                    solver = TwoCaptcha(os.environ["CAPTCHA_API_KEY"])
                    result = solver.recaptcha(sitekey=site_key, url=self.page.url)

                    await self.page.evaluate(
                        f'grecaptcha.getResponse = () => "{result["code"]}"'
                    )
                    await self.page.evaluate("validateLoginCaptcha()")

                    self.logger.info("Captcha solved! Resubmitting form.")

                    await self.sleep(0.3, 1)

                    await self.click(
                        selector="button[type='submit']",
                        navigation=True,
                        navigation_options={
                            "waitUntil": "networkidle0",
                            "timeout": 60000,
                        },
                    )

                    await self.sleep(3, 4)

                    return True
                else:
                    raise LoginOrRegistrationError(f"{error_class}: {error_text}")

        return False

    async def _handle_generic_errors(
        self, error: Exception, callback: Callable, *args, **kwargs
    ):
        if not self.recovery_attempted:
            await self.save_screenshot(
                "screenshots", f"recovery_{callback.__name__}.png"
            )
            self.recovery_attempted = True
            if isinstance(error, TimeoutError):
                self.logger.warning(
                    f"Attempting recovery for the following error: {error}"
                )
                user_info = kwargs.get("user_info", {})
                username = user_info.get("username")
                registered = user_info.get("registered")
                if username and registered:
                    self.logger.info(f"Checking login status of {username}")
                    password = user_info.get("password")
                    logged_in = await self.logged_in(username)
                    if password and not logged_in:
                        self.logger.info("User not logged in, logging in.")
                        await self.login(user_info)

                        self.logger.info("Recovery successful logged in, continuing...")
                        return await callback(*args, **kwargs)
                    elif logged_in:
                        self.logger.info(
                            "Recovery successful already logged in, continuing..."
                        )
                        return await callback(*args, **kwargs)
                elif username:
                    self.logger.info("User not registered, not attempting to login.")
                else:
                    self.logger.info("No username to attempt login")
        else:
            await self.save_screenshot("screenshots", f"error_{callback.__name__}.png")

        raise error

    async def _handle_username_popup(self) -> str | None:
        if await self.is_present('button[data-et-name="suggested_username"]'):
            await self.sleep(0.65, 1.25)

            new_username = await self.page.querySelectorEval(
                'button[data-et-name="suggested_username"]',
                "(element) => element.textContent",
            )

            new_username = new_username.strip()

            await self.click(selector='button[data-et-name="suggested_username"]')

            self.logger.info(f"New username selected: {new_username}")

            await self.click(
                selector='button[type="submit"]',
                navigation=True,
                navigation_options={"waitUntil": "networkidle0", "timeout": 60000},
            )

            await self.sleep(0.5, 0.8)

            return new_username

    async def _handle_sharing_captcha(self) -> bool:
        if await self.is_present(".g-recaptcha-con"):
            captcha_iframe = await self.find("iframe")
            await captcha_iframe._scrollIntoViewIfNeeded()
            captcha_src = await captcha_iframe.getProperty("src")
            captcha_src_val = await captcha_src.jsonValue()

            site_key = re.findall(r"(?<=k=)(.*?)(?=&)", captcha_src_val)[0]
            solver = TwoCaptcha(os.environ["CAPTCHA_API_KEY"])
            result = solver.recaptcha(sitekey=site_key, url=self.page.url)

            await self.page.evaluate(
                f"document.querySelector('#g-recaptcha-response').value = '{result['code']}'"
            )
            await self.page.evaluate("validateResponse()")
            await self.sleep(0.5, 1)

            return True

    async def logged_in(self, username: str) -> bool:
        await self.page.goto("https://poshmark.com")
        if "/feed" in self.page.url:
            if await self.is_present(".user-image"):
                profile_pic = await self.find(".user-image")
                profile_pic_alt_property = await profile_pic.getProperty("alt")
                profile_pic_alt = await profile_pic_alt_property.jsonValue()

                if profile_pic_alt == username:
                    return True

        return False

    async def go_to_closet(self, username: str):
        if f"/closet/{username}" in self.page.url:
            await self.page.reload()
        else:
            await self.page.goto(f"https://poshmark.com/closet/{username}")

        await self.sleep(0.7, 1.2)

        if await self.is_present('button[data-et-name="see_all_listings"]'):
            await self.click(selector="button[data-et-name=see_all_listings")

    async def go_to_listing(self, username: str, listing_id: str):
        if listing_id not in self.page.url or "/listing" not in self.page.url:
            await self.go_to_closet(username)

            # Click listing
            try:
                await self.click(
                    selector=f'a[data-et-prop-listing_id="{listing_id}"].tile__covershot',
                )
            except TimeoutError:
                raise ListingNotFoundError(
                    f"Could not find listing with id: {listing_id}"
                )
        else:
            await self.page.reload()

    async def register(self, user_info: Dict) -> str:
        try:
            self.logger.info(f"delete_me: register in client")
            if "/signup" not in self.page.url:
                await self.page.goto(
                    "https://poshmark.com", waitUntil="domcontentloaded"
                )
                await self.click(
                    selector='a[href="/signup"]',
                    navigation=True,
                    navigation_options={"waitUntil": "networkidle2", "timeout": 60000},
                )
                await self.sleep(0.2, 0.6)

            self.logger.info(f"delete_me: register post nav")
            username: str = user_info["username"]

            await self.type("#firstName", user_info["first_name"])
            await self.type("#lastName", user_info["last_name"])
            await self.type("#email", user_info["email"])
            await self.type('input[name="userName"]', username)
            await self.type("#password", user_info["password"])

            await self.sleep(0.2, 0.8)

            if user_info["gender"] is not None:
                await self.click(selector=".dropdown__selector--select-tag")

                await self.sleep(0.2, 0.8)

                await self.click(
                    selector=f"//div[contains(@class, 'dropdown__link') and contains(text(), '{user_info['gender']}')]",
                    xpath=True,
                )

            self.logger.info(f"delete_me: register pre submit")

            await self.click(
                selector='button[type="submit"]',
                navigation=True,
                navigation_options={"waitUntil": "networkidle2", "timeout": 60000},
            )

            await self.sleep(0.5, 1)

            new_username = await self._handle_username_popup()

            self.logger.info(f"delete_me: register post submit")

            retries = 0
            error_handled = None
            while (
                "/signup" in self.page.url
                and retries < 3
                and error_handled is not False
            ):
                error_handled = await self._handle_form_errors()

                new_username = await self._handle_username_popup()

                retries += 1

            if retries >= 3 or "/signup" in self.page.url:
                raise LoginOrRegistrationError("Max number of retries exceeded")

            if new_username is not None:
                username = new_username

            return username
        except Exception as e:
            return await self._handle_generic_errors(
                e, self.register, user_info=user_info
            )

    async def finish_registration(self, user_info: Dict) -> None:
        try:
            if user_info["profile_picture"]:
                # Upload profile picture to .user-image
                await self.upload_file(
                    ".image-selector__input-img-files", user_info["profile_picture"]
                )

                await self.sleep(1, 2)
                await self.click(selector='button[data-et-name="apply"]')
                await self.sleep(1.5, 2.5)

            # Set shirt/dress size
            size_text = (
                "Dress Size" if user_info["gender"] == "Female" else "Shirt Size"
            )

            try:
                await self.click(
                    selector=f"//div[preceding-sibling::label[contains(text(), '{size_text}')]][@id='set-profile-info-size-dropdown']",
                    xpath=True,
                )
            except TimeoutError as e:
                size_text = "Shirt Size" if size_text == "Dress Size" else "Dress Size"
                await self.click(
                    selector=f"//div[preceding-sibling::label[contains(text(), '{size_text}')]][@id='set-profile-info-size-dropdown']",
                    xpath=True,
                )
            await self.click_random("ul.dropdown__menu--expanded > li", count=1)
            await self.sleep(1, 2)

            # Set shoe size
            await self.click(
                selector="//div[preceding-sibling::label[contains(text(), 'Shoe Size')]][@id='set-profile-info-size-dropdown']",
                xpath=True,
            )
            await self.click_random("ul.dropdown__menu--expanded > li", count=1)
            await self.sleep(1, 2)

            # Enter zipcode
            await self.type(selector='input[name="zip"]', text=user_info["zipcode"])
            await self.sleep(1, 2)
            await self.click(selector='button[type="submit"]', navigation=True)
            await self.sleep(1, 1.5)

            # Select random number of brands
            await self.click_random(selector=".content-grid-item")
            await self.click(selector='button[type="submit"]', navigation=True)

            # Click submit again
            await self.click(selector='button[type="submit"]', navigation=True)
        except Exception as e:
            return await self._handle_generic_errors(
                e,
                self.finish_registration,
                profile_pic_path=user_info["profile_picture"],
                zipcode=user_info["zipcode"],
            )

    async def login(self, user_info: Dict) -> None:
        try:
            username = user_info["username"]
            password = user_info["password"]

            if "/login" not in self.page.url:
                await self.page.goto("https://poshmark.com")
                await self.click(selector='a[href="/login"]')

            await self.sleep(1.5, 2.5)

            await self.type("#login_form_username_email", username)
            await self.type("#login_form_password", password)

            await self.sleep(0.2, 0.6)
            await self.click(
                selector='button[type="submit"]',
                navigation=True,
                navigation_options={"waitUntil": "networkidle2", "timeout": 60000},
            )

            retries = 0
            error_handled = None
            while (
                "/login" in self.page.url and retries < 3 and error_handled is not False
            ):
                error_handled = await self._handle_form_errors()

                retries += 1

            if retries >= 3 and "/login" in self.page.url:
                raise LoginOrRegistrationError("Max number of retries exceeded")
        except Exception as e:
            return await self._handle_generic_errors(e, self.login, user_info=user_info)

    async def list_item(self, user_info: Dict, item_info: Dict) -> Dict:
        try:
            self.logger.info(f"delete_me: listing item in client")
            if await self.is_present('a[href="/sell"]'):
                await self.click(
                    selector='a[href="/sell"]',
                    navigation=True,
                    navigation_options={"waitUntil": "networkidle2", "timeout": 60000},
                )
            elif "create-listing" in self.page.url:
                await self.page.reload()
            else:
                await self.page.goto("https://poshmark.com")
                await self.click(
                    selector='a[href="/sell"]',
                    navigation=True,
                    navigation_options={"waitUntil": "networkidle2", "timeout": 60000},
                )

            await self.sleep(1, 2)

            self.logger.info(f"delete_me: listing item  after nav")

            error_xpath = "//div[contains(@class, 'modal__body') and contains(text(), 'cannot currently perform this')]"
            if await self.is_present(error_xpath, xpath=True):
                raise UserDisabledError("User disabled")

            # Send item images
            await self.upload_file('input[name="img-file-input"]', *item_info["photos"])
            await self.sleep(1, 2)

            await self.click(selector='button[data-et-name="apply"]')
            await self.sleep(1, 2)

            self.logger.info(f"delete_me: sent images")

            # Type item Title
            await self.type('input[data-vv-name="title"]', item_info["title"])
            await self.sleep(0.4, 0.9)

            self.logger.info(f"delete_me: typed title")

            # Type item Description
            await self.type(
                'textarea[data-vv-name="description"]',
                item_info["description"],
                wpm=180,
            )
            await self.sleep(0.4, 0.9)

            self.logger.info(f"delete_me: types description")

            # Put in item Department, Category, and Subcategory
            await self.click(
                selector='//*[@id="content"]/div/div[1]/div[2]/section[3]/div/div[2]/div[1]/div',
                xpath=True,
            )
            await self.sleep(0.4, 0.9)
            await self.click(
                selector=f'//a[@data-et-name="{item_info["department"].lower()}" and @data-et-on-name="category_selection"]',
                xpath=True,
            )
            await self.sleep(0.4, 0.9)
            await self.click(
                selector=f"//li[contains(@class, 'dropdown__menu__item') and contains(., '{item_info['category']}')]",
                xpath=True,
            )
            await self.sleep(0.4, 0.9)
            await self.click(
                selector=f'a[data-et-prop-content="{item_info["subcategory"]}"]'
            )
            await self.sleep(0.5, 1)

            self.logger.info(f"delete_me: selected department")

            # Put in item size
            size_elem = await self.find(selector=f'div[data-test="size"]')
            size_elem_text = await size_elem.getProperty("innerText")
            size_elem_text = await size_elem_text.jsonValue()
            if (
                item_info["size"].lower() == "os"
                and size_elem_text.strip().lower() != "os"
            ):
                await self.click(element=size_elem)
                await self.sleep(0.2, 0.4)
                await self.click(selector="size-One Size")

            elif (
                item_info["size"].lower() != "os"
                and item_info["size"] != size_elem_text.strip()
            ):
                await self.click(element=size_elem)
                await self.sleep(0.2, 0.4)

                await self.find(selector=".navigation--horizontal__tab")

                tab_counter = 0
                current_tab = "Standard"
                size_found = False
                while current_tab != "Custom" and not size_found:
                    self.logger.info(f"delete_me: at {current_tab}")
                    current_tab_elem = await self.find(
                        f'a[data-test="horizontal-nav-{tab_counter}"]'
                    )
                    if tab_counter > 0:
                        await self.click(element=current_tab_elem)

                    size_selector = f"#size-{self.cleanse_selector(item_info['size'])}"
                    if await self.is_present(size_selector):
                        self.logger.info(f"delete_me: found size by {size_selector}")
                        await self.click(selector=size_selector)
                        size_found = True

                    current_tab_inner_text = await current_tab_elem.getProperty(
                        "innerText"
                    )
                    current_tab = await current_tab_inner_text.jsonValue()
                    current_tab = current_tab.strip()
                    tab_counter += 1
                    self.logger.info(f"delete_me: size not found going to next tab")
                    await self.sleep(0.6, 1.2)

                if current_tab == "Custom" and not size_found:
                    self.logger.info(
                        f"delete_me: size not found putting in custom size"
                    )
                    await self.type("#customSizeInput0", item_info["size"])
                    await self.click(
                        selector='//*[@id="content"]/div/div[1]/div[2]/section[4]/div[2]/div[2]/div[1]/div/div[2]/div[2]/div/div/div[1]/ul/li/div/div/button',
                        xpath=True,
                    )
                    await self.sleep(0.4, 0.8)

                    await self.click(selector='button[data-et-name="apply"]')

            self.logger.info(f"delete_me: size inputed")

            # Type in item Brand
            await self.type(
                'input[placeholder="Enter the Brand/Designer"]', item_info["brand"]
            )
            await self.sleep(0.3, 0.9)

            self.logger.info(f"delete_me: brand inputted")

            # Type in Original Price
            await self.type(
                'input[data-vv-name="originalPrice"]', item_info["original_price"]
            )
            await self.sleep(0.3, 0.9)

            self.logger.info(f"delete_me: original price typed")

            # Type in Listing Price
            await self.type(
                'input[data-vv-name="listingPrice"]', item_info["listing_price"]
            )
            await self.sleep(2, 3)

            self.logger.info(f"delete_me: listing price typed")

            # Click Next
            await self.click(selector='button[data-et-name="next"]')
            await self.sleep(0.3, 0.9)

            # Click list item
            await self.click(selector='button[data-et-name="list_item"]')

            latest_url = self.page.url
            attempts = 0
            while "created_listing_id" not in latest_url:
                latest_url = self.page.url
                self.logger.info(f"delete_me: listing item  url - {self.page.url}")
                attempts += 1
                await self.sleep(1)

                if attempts == 15:
                    screenshots_dir = os.path.join(os.getcwd(), "screenshots")
                    screenshot_name = f"listing_attempt.png"
                    os.makedirs(screenshots_dir, exist_ok=True)
                    await self.page.screenshot(
                        {"path": os.path.join(screenshots_dir, screenshot_name)}
                    )
                    self.logger.info(f"Screenshot saved to {screenshot_name}")

            parsed_url = urlparse(latest_url)
            query_params = parse_qs(parsed_url.query)

            try:
                item_info["listing_id"] = query_params["created_listing_id"][0]
            except KeyError:
                pass

            return item_info
        except Exception as e:
            return await self._handle_generic_errors(
                e, self.list_item, user_info=user_info, item_info=item_info
            )

    async def share_listing(self, user_info: Dict, listing_id: str) -> None:
        try:
            username = user_info["username"]
            shared = False
            share_success = False
            retries = 0

            while not shared and retries < 3:
                await self.go_to_closet(username)

                # Click share button
                try:
                    await self.click(
                        selector=f'div[data-et-prop-listing_id="{listing_id}"].social-action-bar__share',
                        navigation=True,
                        navigation_options={
                            "waitUntil": "networkidle0",
                            "timeout": 30000,
                        },
                    )
                except TimeoutError:
                    raise ListingNotFoundError(
                        f"Could not find listing with id: {listing_id}"
                    )
                await self.sleep(1.5, 2)

                # Click share to my followers
                await self.click(selector=".internal-share__link")

                try:
                    flash_message_elem = await self.find(selector="#flash__message")

                    flash_message_inner_text = await flash_message_elem.getProperty(
                        "innerText"
                    )
                    flash_message = await flash_message_inner_text.jsonValue()
                    share_success = flash_message.strip() == "Shared Successfully"
                    shared = True

                    captcha = await self._handle_sharing_captcha()

                    if captcha:
                        shared = False
                        self.logger.info("Captcha solved! Re-sharing.")

                except TimeoutError:
                    shared = False

                retries += 1

            if not share_success and shared:
                raise ShareError("Not successfully shared")
        except (ListingNotFoundError, ShareError) as e:
            raise e
        except Exception as e:
            return await self._handle_generic_errors(
                e, self.share_listing, user_info=user_info, listing_id=listing_id
            )

    async def send_offers_to_likers(
        self, user_info: Dict, listing_id: str, offer: int
    ) -> None:
        try:
            username = user_info["username"]
            await self.go_to_listing(username, listing_id)
            await self.sleep(1, 1.6)

            # Click price drop button
            await self.click(selector='button[data-et-name="price_drop"]')
            await self.sleep(0.3, 0.8)

            # Click private button
            await self.click(selector='button[data-et-name="make_offer_to_likers"]')
            await self.sleep(1, 1.5)

            if not await self.is_present(
                'button[data-et-name="apply_offer"]',
            ):
                await self.click(selector=".btn--primary")
                raise NoLikesError(f"No likes on the listing: {listing_id}")

            await self.type('input[name="offer"]', str(offer))
            await self.sleep(2, 2.5)

            await self.click(selector=".offer-model__shipping-discount")
            await self.sleep(0.3, 0.6)

            await self.click(selector='a[data-et-name="shipping_discount_item"]')
            await self.sleep(0.3, 0.6)

            await self.click(selector='button[data-et-name="apply_offer"]')
            await self.sleep(2, 3)

            await self.click(
                selector='//button[contains(text(), "Continue")]', xpath=True
            )
            await self.sleep(0.5, 1)
        except (NoLikesError, ListingNotFoundError) as e:
            raise e
        except Exception as e:
            return await self._handle_generic_errors(
                e,
                self.send_offers_to_likers,
                user_info=user_info,
                listing_id=listing_id,
                offer=offer,
            )

    async def check_offers(
        self, user_info: Dict, listing_id: str, lowest_price: int
    ) -> None:
        try:
            await self.page.goto(
                f"https://poshmark.com/posts/{listing_id}/active_offers?pageName=ACTIVE_OFFERS&pageType=new"
            )

            if await self.is_present(".active-offers__content__empty-image"):
                raise NoActiveOffersError("No active offers")

            all_offers = await self.find_all(".active-offers__content")

            for index in range(len(all_offers)):
                offers = await self.find_all(".active-offers__content")
                offer = offers[index]
                status_element = await offer.querySelector(".tc--g")
                status_text = await self.page.evaluate(
                    "(element) => element.textContent", status_element
                )

                if status_text.strip() == "New Counteroffer":
                    await self.click(element=offer, navigation=True)

                    chat_bubbles = await self.find_all(".chat-bubble")
                    counter_offer_locator = f'div[data-test="offer_details_offer_interaction_{len(chat_bubbles)}"]'
                    counter_offer_elem = await self.find(counter_offer_locator)
                    counter_offer_message = await self.page.evaluate(
                        "(element) => element.textContent", counter_offer_elem
                    )

                    counter_offer_match = re.search(
                        r"(offered|counteroffered) \$(\d+)", counter_offer_message
                    )
                    counter_offer = int(counter_offer_match.group(2))

                    if counter_offer > lowest_price:
                        await self.click(selector='button[data-et-name="accept_offer"]')
                        await self.sleep(5)
                        await self.click(
                            selector="/html/body/div[2]/main/div[2]/div/div[2]/div[5]/div[3]/div[2]/div[3]/button[2]",
                            xpath=True,
                        )

                        await self.sleep(8)
                    else:
                        last_offer_locator = f'div[data-test="offer_details_offer_interaction_{len(chat_bubbles) - 1}"]'

                        last_offer_elem = await self.find(last_offer_locator)
                        last_offer_message = await self.page.evaluate(
                            "(element) => element.textContent", last_offer_elem
                        )

                        last_offer_match = re.search(
                            r"(offered|counteroffered) \$(\d+)", last_offer_message
                        )
                        last_offer = int(last_offer_match.group(2))
                        new_offer = int(last_offer * 0.9)

                        await self.click(
                            selector='button[data-et-name="counter_offer"]'
                        )

                        await self.sleep(2)

                        await self.type('input[name="offer"]', str(new_offer))
                        await self.sleep(2)
                        await self.click(selector='button[data-et-name="submit"]')
                        await self.sleep(1)

                    await self.page.goto(
                        f"https://poshmark.com/posts/{listing_id}/active_offers?pageName=ACTIVE_OFFERS&pageType=new"
                    )
        except (ListingNotFoundError, NoActiveOffersError) as e:
            raise e
        except Exception as e:
            return await self._handle_generic_errors(
                e, self.check_offers, user_info=user_info, listing_id=listing_id
            )

    async def report_user(
        self, user_info: Dict, username: str, report_type: str
    ) -> None:
        try:
            await self.go_to_closet(username)

            await self.click(selector=".ellipses-dot")
            await self.sleep(0.4, 0.8)

            await self.click(
                selector="//div[contains(@class, 'dropdown__link') and contains(., 'Report User')]",
                xpath=True,
            )
            await self.sleep(1, 2)

            await self.click(selector=".dropdown__selector--select-tag")
            await self.sleep(0.3, 0.6)

            await self.click(
                selector=f"//div[contains(@class, 'dropdown__link') and contains(., '{report_type}')]",
                xpath=True,
            )
            await self.sleep(0.3, 0.6)

            await self.click(selector=".btn--primary")
            await self.sleep(0.3, 0.8)

        except Exception as e:
            return await self._handle_generic_errors(
                e,
                self.report_user,
                user_info=user_info,
                username=username,
                report_type=report_type,
            )

    async def check_comments(
        self, user_info: Dict, listing_id: str, bad_words: List[Dict]
    ) -> None:
        try:
            report_type_mapping = {
                "Spam": "Spam",
                "Transaction Off Poshmark": "Non-PM Transactions",
                "Offensive Comment": "Harassment",
                "Harassment": "Harassment",
            }

            await self.go_to_listing(user_info["username"], listing_id)

            # Select all comment elements
            try:
                comments = await self.find_all(".comment-item__container")
            except TimeoutError:
                comments = []

            # Iterate through each comment
            for comment in comments:
                # Get the comment text content
                comment_item_text = await comment.querySelector(".comment-item__text")
                comment_text = await self.page.evaluate(
                    "(element) => element.textContent", comment_item_text
                )

                # Check if the comment contains any bad words
                for bad_word in bad_words:
                    word = bad_word["word"]

                    if word.lower() in comment_text.lower():
                        report_type = bad_word["report_type"]

                        report_button = await comment.querySelector(
                            'a[data-et-name="report_comment"].comment-item__actions'
                        )
                        if report_button:
                            username_elem = await comment.querySelector(
                                'a[data-et-name="username"]'
                            )
                            username = None
                            if username_elem:
                                username = await self.page.evaluate(
                                    "(element) => element.textContent", username_elem
                                )
                                username = username.strip()

                            await report_button.click()
                            await self.sleep(0.3, 0.7)

                            await self.click(selector=".dropdown__selector--select-tag")
                            await self.sleep(0.3, 0.6)

                            await self.click(
                                selector=f"//div[contains(@class, 'dropdown__link') and contains(text(), '{report_type}')]",
                                xpath=True,
                            )
                            await self.sleep(0.3, 0.6)
                            await self.click(selector=".btn--primary")

                            await self.report_user(
                                user_info, username, report_type_mapping[report_type]
                            )
        except ListingNotFoundError as e:
            raise e

        except Exception as e:
            return await self._handle_generic_errors(
                e,
                self.check_comments,
                user_info=user_info,
                listing_id=listing_id,
                bad_words=bad_words,
            )

    async def like_follow_share(self, user_info: Dict) -> None:
        try:
            feeds = [
                "category/Women",
                "category/Men",
                "category/Kids",
                "category/Home",
                "category/Electronics",
                "category/Pets",
                "category/Women-Makeup",
            ]
            chosen_feed = random.choice(feeds)

            listings = []
            retries = 1

            while not listings and retries < 3:
                try:
                    if chosen_feed not in self.page.url:
                        await self.page.goto(
                            f"https://poshmark.com/{chosen_feed}",
                            waitUntil="networkidle2",
                            timeout=30000,
                        )
                    else:
                        await self.page.reload(
                            waitUntil="networkidle2",
                            timeout=30000,
                        )

                    await self.sleep(3, 4)

                    if await self.is_present('button[data-et-name="see_all_listings"]'):
                        await self.click(
                            selector='button[data-et-name="see_all_listings"]'
                        )

                    listings = await self.find_all(".card")
                except TimeoutError:
                    pass

                retries += 1

            if not listings:
                self.logger.warning(f"Could not find listings after {retries} attempts")
                return

            listings_to_action: List[ElementHandle] = random.sample(
                listings, k=random.randint(5, 10)
            )

            seller_profiles = []
            for listing in listings_to_action:
                self.logger.info("On a listing")
                try:
                    like_button = await listing.querySelector(".like")
                    self.logger.info("After getting like button")
                    if like_button:
                        await self.click(element=like_button)
                        await self.sleep(0.2, 0.4)
                        self.logger.info("Liked")
                except TimeoutError:
                    pass

                try:
                    share_button = await listing.querySelector(".share-gray-large")
                    self.logger.info("After getting like share button")
                    if share_button:
                        await self.click(element=share_button)

                        await self.click(selector=".internal-share__link")
                        await self.sleep(1, 2)

                        await self._handle_sharing_captcha()

                        self.logger.info("Shared")
                except TimeoutError:
                    pass

                seller_profile = await listing.querySelectorEval(
                    "a.tile__creator", "a => a.href"
                )
                self.logger.info("After getting seller profile")
                if seller_profile:
                    seller_profiles.append(seller_profile)
                    self.logger.info("Added seller profile")

            for profile in seller_profiles:
                try:
                    await self.page.goto(profile, timeout=10000)
                    await self.sleep(0.4, 0.7)
                    await self.click(selector='button[data-et-name="follow_user"]')
                except TimeoutError:
                    self.logger.info(f"Timeout while going to {profile}. Skipping...")

        except Exception as e:
            return await self._handle_generic_errors(
                e, self.like_follow_share, user_info=user_info
            )
