import boto3
import datetime
import os
import pickle
import pytz
import random
import re
import requests
import time
import traceback

from django.conf import settings
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.proxy import Proxy, ProxyType
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth

from core.models import Campaign, Offer


class Captcha:
    def __init__(self, google_key, page_url, logger):
        self.request_id = None
        self.google_key = google_key
        self.page_url = page_url
        self.logger = logger
        self.captcha_api_key = os.environ['CAPTCHA_API_KEY']

    def send_captcha(self):
        url = 'https://2captcha.com/in.php'
        params = {
            'key': self.captcha_api_key,
            'method': 'userrecaptcha',
            'googlekey': self.google_key,
            'pageurl': self.page_url,
            'json': '1'
        }
        response = requests.get(url, params=params, timeout=30).json()
        if response['status'] == 1:
            self.request_id = response['request']
            return True
        else:
            self.logger.error(f'reCaptcha request failed! Error code: {response["request"]}')
            return False

    def get_response(self):
        url = 'https://2captcha.com/res.php'
        params = {
            'key': self.captcha_api_key,
            'json': 1,
            'action': 'get',
            'id': self.request_id
        }
        response = requests.get(url, params=params, timeout=30).json()

        if response['status'] == 0:
            if 'ERROR' in response['request']:
                self.logger.error(f"[!] Captcha error: {response['request']}")
                if response['request'] == 'ERROR_CAPTCHA_UNSOLVABLE':
                    return -2
                return -1
            return None
        else:
            return response['request']

    def solve_captcha(self):
        self.send_captcha()
        time.sleep(20)

        while True:
            response = self.get_response()
            if response:
                if response == -1:
                    return -1
                elif response == -2:
                    return None
                else:
                    return response
            time.sleep(5)


class BaseClient:
    def __init__(self, logger, proxy_ip=None, proxy_port=None, cookies_filename='cookies'):
        proxy = Proxy()
        hostname = proxy_ip if proxy_ip and proxy_port else ''
        port = proxy_port if proxy_ip and proxy_port else ''
        proxy.proxy_type = ProxyType.MANUAL if proxy_ip and proxy_port else ProxyType.SYSTEM
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.114 Safari/537.36'

        if proxy_ip:
            proxy.http_proxy = f'{hostname}:{port}'
            proxy.ssl_proxy = f'{hostname}:{port}'

        capabilities = webdriver.DesiredCapabilities.CHROME
        proxy.add_to_capabilities(capabilities)

        self.cookies_path = '/bot_data/cookies'
        self.logger = logger
        self.web_driver = None
        self.web_driver_options = Options()
        self.web_driver_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.web_driver_options.add_experimental_option('useAutomationExtension', False)
        self.web_driver_options.add_experimental_option('prefs', {"enable_do_not_track": True})
        self.web_driver_options.add_argument('--disable-extensions')
        self.web_driver_options.add_argument('--headless')
        self.web_driver_options.add_argument(f'user-agent={user_agent}')
        self.web_driver_options.add_argument('--incognito')
        self.web_driver_options.add_argument('--no-sandbox')
        self.web_driver_options.add_argument("--disable-bundled-ppapi-flash")
        self.web_driver_options.add_argument("--disable-plugins-discovery")
        # self.web_driver_options.add_argument('--disable-blink-features=AutomationControlled')

        self.cookies_filename = cookies_filename

        if not os.path.isdir('/log_images'):
            os.mkdir('log_images')

    def __enter__(self):
        self.open()

        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def open(self):
        """Used to open the selenium web driver session"""
        self.web_driver = webdriver.Chrome('/chrome_clients/chromedriver', options=self.web_driver_options)
        stealth(self.web_driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                )
        tz_params = {'timezoneId': 'America/New_York'}
        self.web_driver.execute_cdp_cmd('Emulation.setTimezoneOverride', tz_params)
        if '--headless' in self.web_driver_options.arguments:
            self.web_driver.set_window_size(1920, 1080)

    def close(self):
        """Closes the selenium web driver session"""
        self.web_driver.quit()

    def locate(self, by, locator, location_type=None):
        """Locates the first elements with the given By"""
        wait = WebDriverWait(self.web_driver, 5)
        if location_type:
            if location_type == 'visibility':
                return wait.until(expected_conditions.visibility_of_element_located((by, locator)))
            elif location_type == 'clickable':
                return wait.until(expected_conditions.element_to_be_clickable((by, locator)))
            else:
                return None
        else:
            return wait.until(expected_conditions.presence_of_element_located((by, locator)))

    def locate_all(self, by, locator, location_type=None):
        """Locates all web elements with the given By and returns a list of them"""
        wait = WebDriverWait(self.web_driver, 5)
        if location_type:
            if location_type == 'visibility':
                return wait.until(expected_conditions.visibility_of_all_elements_located((by, locator)))
            else:
                return None
        else:
            return wait.until(expected_conditions.presence_of_all_elements_located((by, locator)))

    def is_present(self, by, locator):
        """Checks if a web element is present"""
        try:
            self.web_driver.find_element(by=by, value=locator)
        except (NoSuchElementException, TimeoutException):
            return False
        return True

    def sleep(self, lower, upper=None):
        """Will simply sleep and log the amount that is sleeping for, can also be randomized amount of time if given the
        upper value"""
        seconds = random.randint(lower, upper) if upper else lower

        if seconds:
            if seconds > 60:
                duration = seconds / 60
                word = 'minutes'
            else:
                duration = seconds
                word = 'second' if seconds == 1 else 'seconds'

            self.logger.info(f'Sleeping for about {round(duration, 2)} {word}')
            time.sleep(seconds)

    def save_cookies(self):
        self.logger.info('Saving cookies')

        if not os.path.exists(self.cookies_path):
            os.mkdir(self.cookies_path)

        with open(f'{self.cookies_path}/{self.cookies_filename}.pkl', 'wb') as file:
            pickle.dump(self.web_driver.get_cookies(), file)
        self.logger.info('Cookies successfully saved')

    def load_cookies(self):
        self.logger.info('Loading Cookies')
        filename = f'{self.cookies_path}/{self.cookies_filename}.pkl'

        try:
            if os.path.exists(filename):
                if os.path.getsize(filename) > 0:
                    with open(filename, 'rb') as cookies:
                        for cookie in pickle.load(cookies):
                            self.web_driver.add_cookie(cookie)
                        self.web_driver.refresh()
                        self.sleep(2)
                        self.logger.info('Cookies loaded successfully')
                        return True
            else:
                self.logger.warning('No cookies found to load')
                return False
        except Exception:
            self.logger.debug(traceback.format_exc())
            if os.path.exists(filename):
                os.remove(filename)
                self.logger.warning('Problem with cookie file: File Deleted')
            else:
                self.logger.warning('Cookies not loaded: Cookie file not found')
            return False

    def bot_check(self):
        self.logger.info('Starting first bot test')
        self.web_driver.get('https://bot.sannysoft.com')
        self.sleep(3)

        self.web_driver.save_screenshot('/log_images/bot_results1.png')
        self.logger.info('First bot test complete')

        self.logger.info('Starting VPN test')
        self.web_driver.get('https://bot.incolumitas.com/proxy_detect.html')
        self.sleep(10)

        self.web_driver.save_screenshot('/log_images/bot_results_vpn.png')
        self.logger.info('VPN test complete')

        tests_failed = self.is_present(By.XPATH, "//span[@style='color: red;']")
        if tests_failed:
            failed_tests = self.locate_all(By.XPATH, "//span[@style='color: red;']")
            for failed_test in failed_tests:
                failed_test_name = failed_test.find_element(By.XPATH, './../..')
                failed_test_id = failed_test.get_property('id')
                button_id =failed_test_id.replace('res', 'data')
                more_info_button = self.locate(By.ID, button_id)
                more_info_button.click()

                failed_test_data = self.locate(By.ID, 'display-test-data')
                self.logger.info(f'Failed Test: {failed_test_name.text}\n\nTest Data Results:\n{failed_test_data.text}')
                failed_test_close_btn = self.locate(By.XPATH, '/html/body/section/div/div/div/div/div[3]/div[2]/header/button')
                failed_test_close_btn.click()
        else:
            self.logger.info('All VPN tests passed')

        self.logger.info('Starting second bot test')
        self.web_driver.get('https://bot.incolumitas.com/')
        self.sleep(4)

        new_tests = self.locate(By.ID, 'new-tests')
        self.logger.info(f'New test results:\n{new_tests.text}')

        old_tests = self.locate(By.ID, 'detection-tests')
        self.logger.info(f'Old test results:\n{old_tests.text}')

        data_center_ip = self.locate(By.ID, 'datacenter-ip-api-data')
        self.logger.info(f'Data center IP results:\n{data_center_ip.text}')

        headers = self.locate(By.ID, 'httpHeaders')
        self.logger.info(f'HTTP Headers:\n{headers.text}')

        tls_fingerprint = self.locate(By.ID, 'tls-fingerprint')
        self.logger.info(f'TSL Fingerprint:\n{tls_fingerprint.text}')

        navigation_prop = self.locate(By.ID, 'webWorkerRes')
        self.logger.info(f'Web Worker Navigation Properties:\n{navigation_prop.text}')

        self.logger.info('Starting third bot test')
        self.web_driver.get('https://nowsecure.nl')
        self.sleep(60*3)

        self.web_driver.save_screenshot('/log_images/bot_results3.png')
        self.logger.info('Third test complete')

        self.logger.info('All tests complete')


class PoshMarkClient(BaseClient):
    def __init__(self, campaign: Campaign, logger, proxy_hostname=None, proxy_port=None):
        proxy_hostname = proxy_hostname if proxy_hostname else ''
        proxy_port = proxy_port if proxy_port else ''
        super(PoshMarkClient, self).__init__(logger, proxy_hostname, proxy_port, campaign.posh_user.username)

        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)
        self.bucket = s3_client.Bucket(settings.AWS_STORAGE_BUCKET_NAME)
        self.posh_user = campaign.posh_user
        self.campaign = campaign
        self.requests_proxy = {}

        if proxy_hostname and proxy_port:
            self.requests_proxy['https'] = f'http://{proxy_hostname}:{proxy_port}'

        if not os.path.isdir(f'/log_images/{self.campaign.title}'):
            os.mkdir(f'/log_images/{self.campaign.title}')

    def handle_error(self, error_message, filename):
        image_path = f'/log_images/{self.campaign.title}/{filename}'
        self.logger.debug(f'{traceback.format_exc()}')
        self.web_driver.save_screenshot(image_path)
        self.logger.error(error_message)
        is_logged_in = self.check_logged_in()
        if is_logged_in:
            is_inactive = self.check_inactive()
            if is_inactive:
                self.posh_user_inactive()
                return False
            return None
        elif is_logged_in is False:
            self.login()
            return None
        return None

    def posh_user_inactive(self):
        self.posh_user.is_active = False
        self.posh_user.save()

    def check_for_errors(self):
        """This will check for errors on the current page and handle them as necessary"""
        image_name = f'/log_images/{self.campaign.title}/error_check.png'
        self.web_driver.save_screenshot(image_name)
        self.logger.info('Checking for errors')
        captcha_errors = [
            'Invalid captcha',
            'Please enter your login information and complete the captcha to continue.'
        ]
        error_classes = ['form__error-message', 'base_error_message', 'error_banner']
        present_error_classes = []

        for error_class in error_classes:
            if self.is_present(By.CLASS_NAME, error_class):
                present_error_classes.append(error_class)

        if not present_error_classes:
            self.logger.info('No known errors encountered')
            return None

        for present_error_class in present_error_classes:
            if 'form__error' in present_error_class:
                errors = self.locate_all(By.CLASS_NAME, present_error_class)
                error_texts = [error.text for error in errors]
                self.logger.error(f"The following form errors were found: {','.join(error_texts)}")

                return 'ERROR_FORM_ERROR'
            else:
                error = self.locate(By.CLASS_NAME, present_error_class)
                if error.text == 'Invalid Username or Password':
                    self.logger.error(f'Invalid Username or Password')

                    return 'ERROR_USERNAME_PASSWORD'

                elif error.text in captcha_errors:
                    self.web_driver.save_screenshot(f'/log_images/{self.campaign.title}/captcha.png')
                    self.logger.warning('Captcha encountered')
                    captcha_iframe = self.locate(By.TAG_NAME, 'iframe', location_type='visibility')
                    captcha_src = captcha_iframe.get_attribute('src')
                    google_key = re.findall(r'(?<=k=)(.*?)(?=&)', captcha_src)[0]

                    captcha_solver = Captcha(google_key, self.web_driver.current_url, self.logger)
                    captcha_response = captcha_solver.solve_captcha()
                    retries = 1

                    while captcha_response is None and retries != 5:
                        self.logger.warning('Captcha not solved. Retrying captcha again...')
                        captcha_response = captcha_solver.solve_captcha()
                        retries += 1

                    if retries == 5 and captcha_response is None:
                        self.logger.error(f'2Captcha could not solve the captcha after {retries} attempts')
                    elif captcha_response == -1:
                        self.logger.error('Exiting after encountering an error with the captcha.')
                    else:
                        word = 'attempt' if retries == 1 else 'attempts'
                        self.logger.info(f'2Captcha successfully solved captcha after {retries} {word}')
                        # Set the captcha response
                        self.web_driver.execute_script(f'grecaptcha.getResponse = () => "{captcha_response}"')
                        self.web_driver.execute_script('validateLoginCaptcha()')

                    return 'CAPTCHA'
                else:
                    self.logger.error('Unknown error encountered')

                    return 'UNKNOWN'

    def check_listing_timestamp(self, listing_title):
        """Given a listing title will check the last time the listing was shared"""
        try:
            self.logger.info(f'Checking the timestamp on following item: {listing_title}')

            self.go_to_closet()

            listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
            for listed_item in listed_items:
                title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                if title.text == listing_title:
                    listing_button = listed_item.find_element(By.CLASS_NAME, 'tile__covershot')
                    listing_button.click()

                    self.sleep(1)
                    timestamp_element = self.locate(
                        By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[1]/div[1]/header/div/div/div/div'
                    )
                    timestamp = timestamp_element.text

                    timestamp = timestamp[8:]
                    elapsed_time = 9001

                    self.logger.info(f'Timestamp: {timestamp}')

                    space_index = timestamp.find(' ')

                    if timestamp == 'now':
                        elapsed_time = 0
                    elif timestamp[:space_index] == 'a':
                        elapsed_time = 60
                    elif timestamp[:space_index].isnumeric():
                        offset = space_index + 1
                        second_space_index = timestamp[offset:].find(' ') + offset
                        unit = timestamp[offset:second_space_index]

                        if unit == 'secs':
                            elapsed_time = int(timestamp[:space_index])
                        elif unit == 'mins':
                            elapsed_time = int(timestamp[:space_index]) * 60
                        elif unit == 'hours':
                            elapsed_time = int(timestamp[:space_index]) * 60 * 60

                    if elapsed_time > 60:
                        hours, remainder = divmod(elapsed_time, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        self.logger.error(f'Sharing does not seem to be working '
                                          f'Elapsed Time: {hours} hours, {minutes} minutes, and {seconds} seconds')
                        return False
                    else:
                        self.logger.info(f'Shared successfully')

                        return True

        except TimeoutException:
            self.handle_error('Error while checking listing timestamp', 'listing_timestamp_error.png')

    def check_inactive(self):
        """Will check if the current user is inactive"""
        try:
            self.logger.info(f'Checking is the following user is inactive: {self.posh_user.username}')

            self.go_to_closet()
            listing_count_element = self.locate(
                By.XPATH, '//*[@id="content"]/div/div[1]/div/div[2]/div/div/nav/ul/li[1]/a'
            )
            # '//*[@id="content"]/div/div[1]/div/div[2]/div/div[2]/nav/ul/li[1]/a'
            listing_count = listing_count_element.text
            index = listing_count.find('\n')
            total_listings = int(listing_count[:index])

            if total_listings > 0 and not self.is_present(By.CLASS_NAME, 'card--small'):
                self.logger.warning('This user does not seem to be active, setting inactive')
                self.posh_user_inactive()
                return True
            else:
                self.logger.info('This user is still active')
                return False

        except Exception:
            image_path = f'/log_images/{self.campaign.title}/check_inactive_error.png'
            self.logger.debug(f'{traceback.format_exc()}')
            self.web_driver.save_screenshot(image_path)
            self.logger.error('Error while checking if inactive')

            return None

    def delete_listing(self, listing_title):
        """Given a listing title will delete the listing"""
        try:
            self.logger.info(f'Deleting the following item: {listing_title}')

            self.go_to_closet()

            listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
            for listed_item in listed_items:
                title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                if title.text == listing_title:
                    listing_button = listed_item.find_element(By.CLASS_NAME, 'tile__covershot')
                    listing_button.click()

                    self.sleep(1)

                    edit_listing_button = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[1]/a')
                    edit_listing_button.click()

                    self.sleep(1, 2)

                    delete_listing_button = self.locate(
                        By.XPATH, '//*[@id="content"]/div/div[1]/div/div[2]/div/a[1]'
                    )
                    delete_listing_button.click()

                    self.sleep(1)

                    primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                    for primary_button in primary_buttons:
                        if primary_button.text == 'Yes':
                            primary_button.click()

                    self.sleep(5)

                    break

        except Exception:
            self.handle_error('Error while deleting listing', 'delete_listing_error.png')

    def check_logged_in(self):
        """Goes to the login page, if the username field does not exists then it assumes it is logged in"""
        try:
            self.web_driver.get(f'https://poshmark.com/login')
            self.logger.info('Checking if user is signed in')

            self.sleep(1, 2)

            result = 'login' not in self.web_driver.current_url

            if result:
                self.web_driver.save_screenshot(f'/log_images/{self.campaign.title}/logged_in.png')
                self.logger.info('User is logged in')
            else:
                self.web_driver.save_screenshot(f'/log_images/{self.campaign.title}/not_logged_in.png')
                self.logger.info('User is not logged in')

            return result
        except Exception:
            image_path = f'/log_images/{self.campaign.title}/check_logged_in_error.png'
            self.logger.debug(f'{traceback.format_exc()}')
            self.web_driver.save_screenshot(image_path)
            self.logger.error('Error while checking if logged in')

            return None

    def finish_registration(self):
        try:
            self.web_driver.save_screenshot(f'/log_images/{self.campaign.title}/registration_finished.png')
            self.logger.info(f'Successfully registered {self.posh_user.username}')

            # Next Section - Profile
            if self.posh_user.profile_picture:
                self.logger.info('Uploading profile picture')
                profile_picture_name = self.posh_user.profile_picture.name.split('/')[-1]
                self.bucket.download_file(self.posh_user.profile_picture.name, profile_picture_name)

                profile_picture = self.locate(By.XPATH,
                                              '//*[@id="content"]/div/div[2]/div[1]/label/input')
                profile_picture.send_keys(f'/{profile_picture_name}')
            else:
                self.logger.warning('Profile picture not found. Skipping upload')

            self.sleep(1)

            apply_button = self.locate(
                By.XPATH, '//*[@id="content"]/div/div[2]/div[1]/div/div[2]/div[2]/div/button[2]')
            apply_button.click()

            self.sleep(2)

            self.logger.info('Profile picture uploaded')

            next_button = self.locate(By.XPATH, '//button[@type="submit"]')
            next_button.click()

            # Next Section - Select Brands (will not select brands)
            self.sleep(2, 4)  # Sleep for realism
            self.logger.info('Selecting random brands')
            brands = self.web_driver.find_elements(By.CLASS_NAME, 'content-grid-item')
            next_button = self.locate(By.XPATH, '//button[@type="submit"]')

            # Select random brands then click next
            for x in range(random.randint(3, 5)):
                try:
                    brand = random.choice(brands)
                    brand.click()
                except IndexError:
                    pass
            next_button.click()

            # Next Section - All Done Page
            self.sleep(1, 3)  # Sleep for realism
            start_shopping_button = self.locate(By.XPATH, '//button[@type="submit"]')
            start_shopping_button.click()

            self.sleep(3)

            self.save_cookies()

            self.logger.info('Registration Complete')
        except Exception:
            self.handle_error('Error while finishing registration', 'finish_registration.png')

    def register(self, register_retries=0):
        """Will register a given user to poshmark"""
        self.logger.info(f'Registering attempt # {register_retries + 1} {self.posh_user.username}')
        try:
            self.web_driver.get('https://poshmark.com/signup')
            self.logger.info(f'At signup page - {self.web_driver.current_url}')

            self.sleep(2)

            self.logger.info('Filling out form')

            # Get all fields for sign up
            first_name_field = self.locate(By.ID, 'firstName')
            last_name_field = self.locate(By.ID, 'lastName')
            email_field = self.locate(By.ID, 'email')
            username_field = self.locate(By.NAME, 'userName')
            password_field = self.locate(By.ID, 'password')
            gender_field = self.locate(By.CLASS_NAME, 'dropdown__selector--select-tag')

            self.logger.info('Selecting Gender')
            gender_field.click()

            self.sleep(1)

            gender_options = self.web_driver.find_elements(By.CLASS_NAME, 'dropdown__link')

            gender = 'Male' if self.posh_user.gender == 'M' else 'Female'
            for element in gender_options:
                if element.text.strip() == gender:
                    element.click()
                    break

            # Send keys
            self.logger.info('Sending the rest of the fields')
            first_name_field.send_keys(self.posh_user.first_name)
            last_name_field.send_keys(self.posh_user.last_name)
            email_field.send_keys(self.posh_user.email)
            username_field.send_keys(self.posh_user.username)
            password_field.send_keys(self.posh_user.password)
            self.sleep(1)

            # Submit the form
            image_name = f'/log_images/{self.campaign.title}/register_form_submitted.png'
            self.web_driver.save_screenshot(image_name)
            self.logger.info('Form submitted')
            submit_button = self.locate(By.CLASS_NAME, 'signup__footer--submit')
            submit_button.click()

            self.sleep(7)

            attempts = 0
            response = requests.get(f'https://poshmark.com/closet/{self.posh_user.username}',
                                    proxies=self.requests_proxy, timeout=30)
            while attempts < 8 and response.status_code != requests.codes.ok:
                response = requests.get(f'https://poshmark.com/closet/{self.posh_user.username}',
                                        proxies=self.requests_proxy, timeout=30)
                self.logger.warning(
                    f'Closet for {self.posh_user.username} is still not available - Trying again')
                attempts += 1
                self.sleep(5)

            if response.status_code == requests.codes.ok:
                self.finish_registration()
                return True
            else:
                error_code = self.check_for_errors()
                if error_code == 'CAPTCHA':
                    done_button = self.locate(By.XPATH, '//button[@type="submit"]')
                    done_button.click()
                    self.logger.info('Resubmitted form after entering captcha')
                    self.finish_registration()
                    return True
                elif error_code == 'ERROR_FORM_ERROR':
                    self.posh_user_inactive()
                    return False
                elif error_code == 'UNKNOWN':
                    return False
                elif error_code is None:
                    self.logger.info('Assuming registration did not work')
                    return False

        except Exception:
            image_path = f'/log_images/{self.campaign.title}/register_error.png'
            self.logger.debug(f'{traceback.format_exc()}')
            self.web_driver.save_screenshot(image_path)
            self.logger.error('Error while registering')

            return False

    def login(self, login_retries=0):
        """Will go to the Posh Mark home page and log in using waits for realism"""
        try:
            self.logger.info(f'Login attempt # {login_retries + 1} for {self.posh_user.username}')

            self.web_driver.get('https://poshmark.com/login')

            self.logger.info(f'At login page - Current URL: {self.web_driver.current_url}')

            username_field = self.locate(By.ID, 'login_form_username_email')
            password_field = self.locate(By.ID, 'login_form_password')

            self.logger.info('Filling in form')

            username_field.send_keys(self.posh_user.username)

            self.sleep(1)

            password_field.send_keys(self.posh_user.password)
            password_field.send_keys(Keys.RETURN)

            self.logger.info('Form submitted')

            if 'feed' not in self.web_driver.current_url:
                error_code = self.check_for_errors()
                if error_code == 'CAPTCHA':
                    password_field = self.locate(By.ID, 'login_form_password')
                    self.sleep(1)
                    password_field.send_keys(Keys.RETURN)
                    self.logger.info('Form resubmitted')
                    self.sleep(2, 3)
                elif error_code == 'ERROR_FORM_ERROR':
                    self.posh_user_inactive()
                    return False
                elif error_code == 'ERROR_USERNAME_PASSWORD':
                    self.posh_user_inactive()
                    return False
                elif error_code == 'UNKNOWN':
                    return False
                elif error_code is None:
                    pass

            self.sleep(3)

            self.save_cookies()

            return True
        except Exception:
            image_path = f'/log_images/{self.campaign.title}/login_error.png'
            self.logger.debug(f'{traceback.format_exc()}')
            self.web_driver.save_screenshot(image_path)
            self.logger.error('Error while logging in')

            return False

    def go_to_closet(self):
        """Ensures the current url for the web driver is at users poshmark closet"""
        try:
            if self.web_driver.current_url != f'https://poshmark.com/closet/{self.posh_user.username}':
                self.web_driver.get(f'https://poshmark.com/closet/{self.posh_user.username}')
            else:
                self.logger.info(f"Already at {self.posh_user.username}'s closet, refreshing.")
                self.web_driver.refresh()

            show_all_listings_xpath = '//*[@id="content"]/div/div[2]/div/div/section/div[2]/div/div/button'
            if self.is_present(By.XPATH, show_all_listings_xpath):
                show_all_listings = self.locate(By.XPATH, show_all_listings_xpath)
                if show_all_listings.is_displayed():
                    show_all_listings.click()

            self.sleep(1, 2)

        except Exception as e:
            self.handle_error('Error while going to closet', 'go_to_closet_error.png')

    def get_all_listings(self):
        """Goes to a user's closet and returns a list of all the listings, excluding Ones that have an inventory tag"""
        try:
            shareable_listings = []
            sold_listings = []
            reserved_listings = []

            self.logger.info(f'Getting all listings for {self.campaign.posh_user.username}')

            self.go_to_closet()

            if self.is_present(By.CLASS_NAME, 'card--small'):
                listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
                for listed_item in listed_items:
                    title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                    try:
                        icon = listed_item.find_element(By.CLASS_NAME, 'inventory-tag__text')
                    except NoSuchElementException:
                        icon = None

                    if not icon:
                        shareable_listings.append(title.text)
                    elif icon.text == 'SOLD':
                        sold_listings.append(title.text)
                    elif icon.text == 'RESERVED':
                        reserved_listings.append(title.text)

                if shareable_listings:
                    self.logger.info(f"Found the following listings: {','.join(shareable_listings)}")
                else:
                    sold_listings_str = '\n'.join(sold_listings) if sold_listings else 'None'
                    reserved_listings_str = '\n'.join(reserved_listings) if reserved_listings else 'None'

                    self.logger.info(f'Sold Listings: {sold_listings_str}')
                    self.logger.info(f'Reserved Listings: {reserved_listings_str}')
                    image_path = f'/log_images/{self.campaign.title}/no_listings.png'
                    self.web_driver.save_screenshot(image_path)
                    self.logger.info('No shareable listings found')
            else:
                is_logged_in = self.check_logged_in()
                if is_logged_in:
                    is_inactive = self.check_inactive()
                    if is_inactive:
                        self.posh_user_inactive()
                        return False
                    return False
                elif is_logged_in is False:
                    self.login()
                    return None
                return None

            listings = {
                'shareable_listings': shareable_listings,
                'sold_listings': sold_listings,
                'reserved_listings': reserved_listings
            }

            return listings

        except Exception as e:
            self.handle_error('Error while getting all listings', 'get_all_listings_error.png')

    def update_profile(self, update_profile_retries=0):
        """Updates a user profile with their profile picture and header picture"""
        try:
            self.logger.info(f'Profile update Attempt # {update_profile_retries + 1} for {self.campaign.posh_user.username}')

            if self.posh_user.header_picture:
                self.go_to_closet()

                edit_profile_button = self.locate(By.XPATH, '//a[@href="/user/edit-profile"]')
                edit_profile_button.click()

                self.logger.info('Clicked on edit profile button')

                header_picture_name = self.posh_user.header_picture.name.split('/')[-1]
                self.bucket.download_file(self.posh_user.header_picture.name, header_picture_name)

                header_picture = self.locate(By.CLASS_NAME, 'image-selector__input-img-files')
                header_picture.send_keys(f'/{header_picture_name}')

                self.sleep(1)

                apply_button = self.locate(By.XPATH, '//*[@id="content"]/div/div[2]/div/div[1]/div[2]/div/div[2]/div[2]/div/button[2]')
                apply_button.click()

                self.sleep(1, 2)

                save_button = self.locate(By.CLASS_NAME, 'btn--primary')
                save_button.click()

                self.logger.info('Profile saved')

                self.sleep(1, 3)

                return True
            else:
                self.logger.warning('No header picture found to upload')
        except Exception as e:
            self.handle_error('Error while updating profile', 'update_profile_error.png')
            return False

    def list_item(self, listing, listing_images, list_item_retries=0):
        """Will list an item on poshmark for the user"""
        try:
            listing_title = listing.title

            self.logger.info(f'Attempt # {list_item_retries + 1} to list {listing_title} for {self.posh_user.username}')

            self.go_to_closet()

            self.logger.info('Clicking sell button')

            sell_button = self.locate(By.CLASS_NAME, 'sell')
            sell_button.click()

            self.sleep(2)

            self.logger.info(f'Current URL: {self.web_driver.current_url}')

            if self.is_present(By.XPATH, '//*[@id="app"]/main/div[1]/div/div[2]'):
                image_path = f'/log_images/{self.campaign.title}/listing_error.png'
                self.web_driver.save_screenshot(image_path)
                self.logger.error('Error encountered when on the new listing page. Setting user inactive.', image_path)
                self.posh_user_inactive()

                return False
            else:
                listing_category = listing.category
                listing_subcategory = listing.subcategory
                listing_size = listing.size
                listing_brand = listing.brand
                listing_description = listing.description
                listing_original_price = listing.original_price
                listing_listing_price = listing.listing_price
                listing_tags = None
                listing_image_names = []

                self.logger.info('Downloading all of the listing images')

                campaign_folder_exists = os.path.exists(f'/{self.campaign.title}')
                listing_folder_exists = os.path.exists(f'/{self.campaign.title}/{listing.title}')

                if not campaign_folder_exists:
                    os.mkdir(f'/{self.campaign.title}')

                if not listing_folder_exists:
                    os.mkdir(f'/{self.campaign.title}/{listing.title}')

                listing_cover_photo_name = listing.cover_photo.name.split('/')[-1]
                self.bucket.download_file(listing.cover_photo.name, f'/{self.campaign.title}/{listing.title}/{listing_cover_photo_name}')

                for listing_image in listing_images:
                    image_name = listing_image.image.name.split('/')[-1]
                    self.bucket.download_file(listing_image.image.name, f'/{self.campaign.title}/{listing.title}/{image_name}')
                    listing_image_names.append(image_name)

                # Set category and sub category
                self.logger.info('Setting category')
                category_dropdown = self.locate(
                    By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/section[3]/div/div[2]/div[1]/div'
                )
                category_dropdown.click()

                space_index = listing_category.find(' ')
                primary_category = listing_category[:space_index]
                secondary_category = listing_category[space_index + 1:]
                primary_categories = self.locate_all(By.CLASS_NAME, 'p--l--7')
                for category in primary_categories:
                    if category.text == primary_category:
                        category.click()
                        break

                secondary_categories = self.locate_all(By.CLASS_NAME, 'p--l--7')
                for category in secondary_categories[1:]:
                    if category.text == secondary_category:
                        category.click()
                        break

                self.logger.info('Category set')

                self.logger.info('Setting subcategory')

                subcategory_menu = self.locate(By.CLASS_NAME, 'dropdown__menu--expanded')
                subcategories = subcategory_menu.find_elements(By.TAG_NAME,'a')
                subcategory = listing_subcategory
                for available_subcategory in subcategories:
                    if available_subcategory.text == subcategory:
                        available_subcategory.click()
                        break

                self.logger.info('Subcategory set')

                # Set size (This must be done after the category has been selected)
                self.logger.info('Setting size')
                size_dropdown = self.locate(
                    By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/section[4]/div[2]/div[2]/div[1]/div/div[2]/div[1]/div'
                )
                actions = ActionChains(self.web_driver)
                actions.move_to_element(size_dropdown).perform()

                time.sleep(1)

                size_dropdown.click()
                size_buttons = self.locate_all(By.CLASS_NAME, 'navigation--horizontal__tab')

                for button in size_buttons:
                    if button.text == 'Custom':
                        button.click()
                        break

                custom_size_input = self.locate(By.ID, 'customSizeInput0')
                save_button = self.locate(
                    By.XPATH,
                    '//*[@id="content"]/div/div[1]/div[2]/section[4]/div[2]/div[2]/div[1]/div/div[2]/div[2]/div/div/div[1]/ul/li/div/div/button'
                )
                done_button = self.locate(
                    By.XPATH,
                    '//*[@id="content"]/div/div[1]/div[2]/section[4]/div[2]/div[2]/div[1]/div/div[2]/div[2]/div/div/div[2]/button'
                )
                size = listing_size
                custom_size_input.send_keys(size)
                save_button.click()
                done_button.click()

                self.logger.info('Size set')

                self.logger.info('Updating Brand')
                brand_field = self.locate(
                    By.XPATH,
                    '//*[@id="content"]/div/div[1]/div/section[6]/div/div[2]/div[1]/div[1]/div/input'
                )

                brand_field.clear()
                brand_field.send_keys(listing_brand)

                # Upload listing photos, you have to upload the first picture then click apply before moving on to upload
                # the rest, otherwise errors come up.
                self.logger.info('Uploading photos')

                cover_photo_field = self.locate(By.ID, 'img-file-input')
                cover_photo_field.send_keys(f'/{self.campaign.title}/{listing.title}/{listing_cover_photo_name}')
                element = self.locate(By.CLASS_NAME, 'listing-editor__promotion__count')
                self.web_driver.execute_script("return arguments[0].scrollIntoView(true);", element)
                self.web_driver.save_screenshot('cover_photo_upload.png')
                apply_button = self.locate(By.XPATH, '//*[@id="imagePlaceholder"]/div[2]/div[2]/div[2]/div/button[2]')
                apply_button.click()

                self.sleep(1)

                for image in listing_image_names:
                    upload_photos_field = self.locate(By.ID, 'img-file-input')
                    upload_photos_field.clear()
                    upload_photos_field.send_keys(f'/{self.campaign.title}/{listing.title}/{image}')
                    self.sleep(1)

                self.logger.info('Photos uploaded')

                # Get all necessary fields
                self.logger.info('Putting in the rest of the fields')
                title_field = self.locate(
                    By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/section[2]/div[1]/div[2]/div/div[1]/div/div/input'
                )
                description_field = self.locate(
                    By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/section[2]/div[2]/div[2]/textarea'
                )

                input_fields = self.locate_all(By.TAG_NAME, 'input')
                for input_field in input_fields:
                    if input_field.get_attribute('data-vv-name') == 'originalPrice':
                        original_price_field = input_field
                    if input_field.get_attribute('data-vv-name') == 'listingPrice':
                        listing_price_field = input_field

                # Send all the information to their respected fields
                title = listing_title
                title_field.send_keys(title)

                for part in listing_description.split('\n'):
                    description_field.send_keys(part)
                    ActionChains(self.web_driver).key_down(Keys.SHIFT).key_down(Keys.ENTER).key_up(Keys.SHIFT).key_up(
                        Keys.ENTER).perform()

                original_prize = str(listing_original_price)
                original_price_field.send_keys(original_prize)
                listing_price = str(listing_listing_price)
                listing_price_field.send_keys(listing_price)

                if listing_tags:
                    tags_button = self.locate(
                        By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/section[5]/div/div[2]/div[1]/button[1]',
                        'clickable'
                    )
                    self.web_driver.execute_script("arguments[0].click();", tags_button)

                next_button = self.locate(By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/div[2]/button')
                next_button.click()

                self.sleep(1)

                list_item_button = self.locate(
                    By.XPATH, '//*[@id="content"]/div/div[1]/div[2]/div[3]/div[2]/div[2]/div[2]/button'
                )
                list_item_button.click()

                sell_button = self.is_present(By.XPATH, '//*[@id="app"]/header/nav[2]/div[1]/ul[2]/li[2]/a')

                attempts = 0
                self.logger.info('Sell button clicked')
                self.sleep(5)
                image_name = f'/log_images/{self.campaign.title}/not_done_listing.png'

                while not sell_button and attempts < 10:
                    self.web_driver.save_screenshot(image_name)
                    self.logger.warning('Not done listing item. Checking again...')
                    sell_button = self.is_present(By.XPATH, '//*[@id="app"]/header/nav[2]/div[1]/ul[2]/li[2]/a')
                    attempts += 1
                    self.sleep(5)
                else:
                    if attempts >= 10:
                        self.logger.error(f'Attempted to locate the sell button {attempts} times but could not find it.')
                        return False
                    else:
                        self.logger.info('Item listed successfully')

                return True

        except Exception as e:
            return self.handle_error('Error while listing', 'list_item_error.png')

    def share_item(self, listing_title):
        """Will share an item in the closet"""
        try:
            self.logger.info(f'Sharing the following item: {listing_title}')

            self.go_to_closet()

            listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
            for listed_item in listed_items:
                title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                if title.text == listing_title:
                    share_button = listed_item.find_element(By.CLASS_NAME, 'social-action-bar__share')
                    share_button.click()

                    self.sleep(1)

                    to_followers_button = self.locate(By.CLASS_NAME, 'internal-share__link')
                    to_followers_button.click()

                    self.web_driver.save_screenshot(f'/log_images/{self.campaign.title}/item_shared.png')
                    self.logger.info('Item Shared')

                    return self.check_listing_timestamp(listing_title)

        except Exception as e:
            self.handle_error('Error while sharing item', 'share_item_error.png')

    def check_offers(self, listing_title):
        try:
            if self.campaign.mode == Campaign.ADVANCED_SHARING:
                lowest_price = self.campaign.listings.get(title=listing_title).lowest_price
            else:
                lowest_price = self.campaign.lowest_price

            self.logger.info(f'Checking offers for {listing_title}')
            self.web_driver.get('https://poshmark.com/offers/my_offers')

            if self.is_present(By.CLASS_NAME, 'active-offers__content'):
                offers = self.locate_all(By.CLASS_NAME, 'active-offers__content')

                for offer in offers:
                    if listing_title in offer.text:
                        self.logger.info('Offers found')
                        offer.click()

                        listing_price_text = self.locate(By.XPATH, '//*[@id="content"]/div/div[2]/div[2]/div[1]/div/div[2]/h5[2]').text
                        listing_price = int(re.findall(r'\d+', listing_price_text)[-1])

                        active_offers = self.locate_all(By.CLASS_NAME, 'active-offers__content')
                        offer_page_url = self.web_driver.current_url

                        self.logger.info(f'There are currently {len(active_offers)} active offers')
                        for x in range(len(active_offers)):
                            active_offers = self.locate_all(By.CLASS_NAME, 'active-offers__content')
                            active_offer = active_offers[x]
                            active_offer.click()

                            self.sleep(2)
                            try:
                                self.locate_all(By.CLASS_NAME, 'btn--primary')

                                sender_offer = 0
                                receiver_offer = 0
                                chat_bubbles = self.locate_all(By.CLASS_NAME, 'ai--fs')
                                for chat_bubble in reversed(chat_bubbles):
                                    try:
                                        bubble = chat_bubble.find_element(By.XPATH, './/*')
                                        if sender_offer and receiver_offer:
                                            break
                                        elif 'sender' in bubble.get_attribute('class') and not sender_offer:
                                            text = bubble.text
                                            if 'offered' in text:
                                                sender_offer = int(re.findall(r'\d+', text)[-1])
                                            elif 'cancelled' in text:
                                                self.logger.warning(f'Seller cancelled. Message: "{text}"')
                                                break
                                            else:
                                                self.logger.warning(f'Unknown message sent by seller. Message: "{text}"')
                                                break
                                        elif 'receiver' in bubble.get_attribute('class') and not receiver_offer:
                                            text = bubble.text
                                            if 'declined' in text:
                                                receiver_offer = listing_price
                                            elif 'offered' or 'listed' in text:
                                                receiver_offer = int(re.findall(r'\d+', text)[-1])
                                            else:
                                                self.logger.warning(f'Unknown message sent by seller. Message: "{text}"')
                                                break
                                    except NoSuchElementException:
                                        pass

                                if sender_offer:
                                    if sender_offer >= lowest_price or sender_offer >= receiver_offer - 1:
                                        primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                                        for button in primary_buttons:
                                            if button.text == 'Accept':
                                                button.click()
                                                break

                                        self.sleep(2)

                                        primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                                        for button in primary_buttons:
                                            if button.text == 'Yes':
                                                button.click()
                                                self.logger.info(f'Accepted offer at ${sender_offer}.')
                                                self.sleep(5)
                                                break
                                    else:
                                        secondary_buttons = self.locate_all(By.CLASS_NAME, 'btn--tertiary')

                                        if receiver_offer < lowest_price - 4:
                                            for button in secondary_buttons:
                                                if button.text == 'Decline':
                                                    button.click()
                                                    break

                                            self.sleep(1)
                                            primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                                            for button in primary_buttons:
                                                if button.text == 'Yes':
                                                    button.click()
                                                    self.sleep(5)
                                                    break
                                        else:
                                            for button in secondary_buttons:
                                                if button.text == 'Counter':
                                                    button.click()
                                                    break
                                            if receiver_offer <= lowest_price:
                                                new_offer = receiver_offer - 1
                                            else:
                                                new_offer = round(receiver_offer - (receiver_offer * .05))
                                                if new_offer < lowest_price:
                                                    new_offer = lowest_price

                                            counter_offer = new_offer

                                            counter_offer_input = self.locate(By.CLASS_NAME, 'form__text--input')
                                            counter_offer_input.send_keys(str(counter_offer))
                                            self.sleep(2)
                                            primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                                            for button in primary_buttons:
                                                if button.text == 'Submit':
                                                    button.click()
                                                    self.logger.info(f'Buyer offered ${sender_offer}, countered offer sent for ${counter_offer}')
                                                    self.sleep(5)
                                                    break
                                else:
                                    self.logger.warning('Nothing to do on the current offer')
                                    self.logger.debug(f'Our Offer: ${receiver_offer} Sender Offer: ${sender_offer}')
                            except TimeoutException:
                                self.logger.warning('Nothing to do on the current offer, seems buyer has not counter offered.')
                            self.web_driver.get(offer_page_url)
            else:
                self.logger.warning('No offers at the moment')

        except Exception as e:
            self.handle_error('Error while checking offers', 'check_offers_error.png')

    def send_offer_to_likers(self, listing_title):
        """Will send offers to all likers for a given listing"""
        try:
            self.logger.info(f'Sending offers to all likers for the following item: {listing_title}')
            today = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            start_date = datetime.datetime(year=today.year, month=today.month, day=today.day, hour=0, minute=0,
                                           second=0).replace(tzinfo=pytz.utc)
            end_date = datetime.datetime(year=today.year, month=today.month, day=today.day, hour=23, minute=59,
                                         second=59).replace(tzinfo=pytz.utc)

            offers = Offer.objects.filter(
                listing_title=listing_title,
                posh_user=self.campaign.posh_user,
                datetime_sent__range=(start_date, end_date)
            ).order_by('datetime_sent')
            first_offer = offers.first()

            if not first_offer:
                self.go_to_closet()

                listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
                for listed_item in listed_items:
                    title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                    if title.text == listing_title:
                        listing_price_text = listed_item.find_element(By.CLASS_NAME, 'fw--bold').text
                        listing_price = int(re.findall(r'\d+', listing_price_text)[-1])

                        listing_button = listed_item.find_element(By.CLASS_NAME, 'tile__covershot')
                        listing_button.click()

                        self.sleep(2)

                        offer_button = self.locate(
                            By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div/button'
                        )
                        offer_button.click()

                        offer_to_likers_button = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div[2]/div[1]/div[2]/div[2]/div/div[2]/div/button')
                        offer_to_likers_button.click()

                        self.sleep(1)

                        offer_amount = int(listing_price - (listing_price * .1))

                        self.logger.info(f'Sending offers to likers for ${offer_amount}')

                        offer_input = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div[2]/div[1]/div[2]/div[2]/div/form/div[1]/input')
                        offer_input.send_keys(str(offer_amount))

                        self.sleep(2)

                        shipping_dropdown = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div[2]/div[1]/div[2]/div[2]/div/form/div[2]/div[1]/div/div/div/div[1]/div')
                        shipping_dropdown.click()

                        shipping_options = self.locate_all(By.CLASS_NAME, 'dropdown__menu__item')

                        for shipping_option in shipping_options:
                            if shipping_option.text == 'FREE':
                                shipping_option.click()
                                break

                        apply_button = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div[2]/div[1]/div[2]/div[3]/div/button[2]')
                        apply_button.click()

                        done_button = self.locate(By.XPATH, '//*[@id="content"]/div/div/div[3]/div[2]/div[5]/div[2]/div/div[2]/div[2]/div[3]/button')
                        done_button.click()

                        offer = Offer(
                            amount=offer_amount,
                            listing_title=listing_title,
                            posh_user=self.campaign.posh_user,
                            datetime_sent=today
                        )
                        offer.save()

                        self.logger.info('Offers successfully sent!')

                        return True
            else:
                self.logger.info('Not sending another offer the following offer was sent today: ')
                self.logger.info(f'Datetime Sent - {first_offer.datetime_sent} Offer Amount - {first_offer.amount}')

        except Exception as e:
            self.handle_error('Error while sending offer to likers', 'send_offer_to_likers.png')

    def check_news(self):
        """Checks PoshUser's news"""
        try:
            self.logger.info('Checking news')

            self.web_driver.get('https://poshmark.com/feed')

            badge = self.is_present(By.CLASS_NAME, 'badge badge--red badge--right')
            if badge:
                news_nav = self.locate(By.XPATH, '//a[@href="/news"]')
                news_nav.click()

                self.sleep(3, 10)

                for x in range(random.randint(2, 4)):
                    self.random_scroll()
                    self.sleep(5, 10)
            else:
                self.logger.info('No news to check, skipping.')

            self.logger.info('Successfully checked news')

        except Exception:
            self.logger.error(f'{traceback.format_exc()}')
            if not self.check_logged_in():
                self.login()

    def check_comments(self, listing_title):
        """Checks all the comments for a given listing to ensure there are no bad comments, if so it reports them"""
        try:
            self.logger.info(f'Checking the comments for the following item: {listing_title}')

            self.go_to_closet()

            bad_words = ('scam', 'scammer', 'fake', 'replica', 'reported', 'counterfeit', 'stolen', 'chinesecrap')
            reported = False

            listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
            for listed_item in listed_items:
                title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                if title.text == listing_title:
                    listing_button = listed_item.find_element(By.CLASS_NAME, 'tile__covershot')
                    listing_button.click()

                    self.sleep(3)
                    if self.is_present(By.CLASS_NAME, 'comment-item__container'):
                        regex = re.compile('[^a-zA-Z]+')
                        comments = self.locate_all(By.CLASS_NAME, 'comment-item__container')
                        for comment in comments:
                            text = comment.find_element(By.CLASS_NAME, 'comment-item__text').text
                            cleaned_comment = regex.sub('', text.lower())

                            if any([bad_word in cleaned_comment for bad_word in bad_words]):
                                report_button = comment.find_element(By.CLASS_NAME, 'flag')
                                report_button.click()

                                self.sleep(1)

                                primary_buttons = self.locate_all(By.CLASS_NAME, 'btn--primary')
                                for button in primary_buttons:
                                    if button.text == 'Submit':
                                        button.click()
                                        reported = True
                                        self.logger.warning(f'Reported the following comment as spam: {text}')
                                        break
                        if not reported:
                            self.logger.info(f'No comments with the following words: {", ".join(bad_words)}')
                    else:
                        self.logger.info(f'No comments on this listing yet.')
                    break

        except Exception:
            self.logger.error(f'{traceback.format_exc()}')
            if not self.check_logged_in():
                self.login()

    def random_scroll(self, scroll_up=True):
        try:
            self.logger.info('Scrolling randomly')

            height = self.web_driver.execute_script("return document.body.scrollHeight")
            scroll_amount = self.web_driver.execute_script("return window.pageYOffset;")
            lower_limit = 0 - scroll_amount if scroll_up else 0
            upper_limit = height - scroll_amount
            scroll_chosen = random.randint(lower_limit, upper_limit)

            self.logger.debug(f'Amount Scrolled Right Now: {scroll_amount} Scroll Amount Chosen: {scroll_chosen}')

            self.web_driver.execute_script(f"window.scrollBy(0,{scroll_chosen});")
        except Exception:
            self.logger.error(f'{traceback.format_exc()}')

    def follow_random_follower(self):
        """Goes through the user's followers and follows someone randomly back"""
        try:
            self.logger.info('Following a random follower')
            self.go_to_closet()

            self.sleep(3, 5)

            followers_button = self.locate(By.XPATH, '//*[@id="content"]/div/div[1]/div/div[2]/div/div[2]/nav/ul/li[3]/div')
            followers_button.click()

            self.sleep(3, 5)

            for x in range(random.randint(3, 6)):
                self.random_scroll()
                self.sleep(5, 10)

            selected_user = None
            available_users = self.locate_all(By.CLASS_NAME, 'follow-list__item')

            while not selected_user:
                selection = random.choice(available_users)
                follow_button = selection.find_element_by_tag_name('button')

                if follow_button.text.replace(' ', '') == 'Follow':
                    selected_user = selection.find_element(By.CLASS_NAME, 'follow__action__follower ').text
                    actions = ActionChains(self.web_driver)
                    actions.move_to_element(follow_button).perform()

                    self.logger.info(f'The following user was selected to be followed: {selected_user}')

                    self.sleep(3, 5)

                    follow_button.click()

                    self.logger.info(f'Followed {selected_user}')

        except Exception:
            self.logger.error(f'{traceback.format_exc()}')
            if not self.check_logged_in():
                self.login()

    def follow_random_user(self):
        """Goes to poshmark find people and follows a random person"""
        try:
            self.logger.info('Following a random user')

            self.web_driver.get('https://www.poshmark.com/find-people')

            for x in range(random.randint(2, 5)):
                self.random_scroll()
                self.sleep(5, 10)

            sample_size = random.randint(1, 5)
            available_users = self.locate_all(By.CLASS_NAME, 'feed-page')
            selected_users = random.sample(available_users, sample_size) if available_users else []

            for selected_user in selected_users:
                username = selected_user.find_element(By.CLASS_NAME, 'follow__action__follower').text
                follow_button = selected_user.find_element(By.CLASS_NAME, 'follow__action__button')

                self.logger.info(f'The following user was selected to be followed: {username}')

                actions = ActionChains(self.web_driver)
                actions.move_to_element(follow_button).perform()

                self.sleep(5, 8)

                follow_button.click()

                self.logger.info(f'Followed {username}')

                self.sleep(4, 12)

        except Exception as e:
            self.logger.error(f'{traceback.format_exc()}')
            if not self.check_logged_in():
                self.login()

    def go_through_feed(self):
        """Will scroll randomly through the users feed"""
        try:
            self.logger.info('Going through the users feed')

            self.web_driver.get('https://poshmark.com/feed')

            for x in range(random.randint(15, 35)):
                self.random_scroll(scroll_up=False)

                self.sleep(5, 12)

                posts = self.locate_all(By.CLASS_NAME, 'feed__unit')
                for post in posts:
                    if post.is_displayed():
                        try:
                            like_icon = post.find_element(By.CLASS_NAME, 'heart-gray-empty')
                            share_icon = post.find_element(By.CLASS_NAME, 'share-gray-large')
                            post_title = post.find_element(By.CLASS_NAME, 'feed__unit__header__title--medium').text
                            listing_title = post.find_element(By.CLASS_NAME, 'feed__summary__title-block').text

                            index = post_title.find(' ')
                            username = post_title[:index]

                            self.sleep(2, 3)

                            if random.random() < .30:
                                actions = ActionChains(self.web_driver)
                                actions.move_to_element(like_icon).perform()

                                like_icon.click()

                                self.logger.info(f'Just liked {listing_title} posted by {username}')

                            if random.random() < .30:
                                actions = ActionChains(self.web_driver)
                                actions.move_to_element(share_icon).perform()

                                share_icon.click()

                                self.sleep(1)

                                to_my_followers = self.locate(By.CLASS_NAME, 'share-wrapper__icon-container')
                                to_my_followers.click()

                                self.logger.info(f'Just shared {listing_title} posted by {username}')

                            break
                        except (NoSuchElementException, TimeoutException):
                            pass

                self.sleep(5, 10)

        except:
            self.logger.error(f'{traceback.format_exc()}')
            if not self.check_logged_in():
                self.login()

    def check_ip(self):
        self.web_driver.get('https://www.ipchicken.com/')
        ip = self.locate(By.XPATH, '/html/body/table[2]/tbody/tr/td[3]/p[2]/font/b').text

        self.logger.info(f'IP: {ip}')


class PublicPoshMarkClient(BaseClient):
    def __init__(self, logger):
        super(PublicPoshMarkClient, self).__init__(logger)

    def get_all_listings(self, username):
        """Goes to a user's closet and returns a list of all the listings"""
        shareable_listings = []
        sold_listings = []
        reserved_listings = []

        self.logger.info(f'Getting all listings for {username}')

        self.web_driver.get(f'http://poshmark.com/closet/{username}')

        self.sleep(3)

        if self.is_present(By.CLASS_NAME, 'card--small'):
            listed_items = self.locate_all(By.CLASS_NAME, 'card--small')
            for listed_item in listed_items:
                title = listed_item.find_element(By.CLASS_NAME, 'tile__title')
                try:
                    icon = listed_item.find_element(By.CLASS_NAME, 'inventory-tag__text')
                except NoSuchElementException:
                    icon = None

                if not icon:
                    shareable_listings.append(title.text)
                elif icon.text == 'SOLD':
                    sold_listings.append(title.text)
                elif icon.text == 'RESERVED':
                    reserved_listings.append(title.text)

            sold_listings_str = ', '.join(sold_listings) if sold_listings else 'None'
            reserved_listings_str = ', '.join(reserved_listings) if reserved_listings else 'None'
            shareable_listings_str = ', '.join(shareable_listings) if shareable_listings else 'None'

            self.logger.info(f'Sold Listings: {sold_listings_str}')
            self.logger.info(f'Reserved Listings: {reserved_listings_str}')
            self.logger.info(f'Shareable Listings: {shareable_listings_str}')
        else:
            self.logger.info('No listing cards found')

        listings = {
            'shareable_listings': shareable_listings,
            'sold_listings': sold_listings,
            'reserved_listings': reserved_listings
        }

        return listings

    def check_inactive(self, username):
        """Will check if the current user is inactive"""
        self.logger.info(f'Checking is the following user is inactive: {username}')

        self.web_driver.get(f'https://poshmark.com/closet/{username}')

        self.sleep(3)

        listing_count_element = self.locate(
            By.XPATH, '//*[@id="content"]/div/div[1]/div/div[2]/div/div/nav/ul/li[1]/a'
        )
        listing_count = listing_count_element.text
        index = listing_count.find('\n')
        total_listings = int(listing_count[:index])

        if total_listings > 0 and not self.is_present(By.CLASS_NAME, 'card--small'):
            self.logger.warning('This user does not seem to be active, setting inactive')

            return False
        else:
            self.logger.info('This user is still active')
            return True
