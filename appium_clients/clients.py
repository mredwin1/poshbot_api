import boto3
import os
import random
import requests
import time
import traceback

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from bs4 import BeautifulSoup
from decimal import Decimal
from django.conf import settings
from django.core.files import File
from django.utils.text import slugify
from ppadb.client import Client as AdbClient
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from typing import List

from core.models import Campaign, ListedItem, ListingImage, Device, Proxy, PoshUser, AppData, LogGroup

APPIUM_SERVER_URL = f'http://{os.environ.get("LOCAL_SERVER_IP")}:4723'


class AppiumClient:
    def __init__(self, device_serial: str, system_port: int, mjpeg_server_port: int, logger: LogGroup, capabilities: dict):
        self.driver = None
        self.logger = logger
        self.files_sent = []

        capabilities['udid'] = device_serial
        capabilities['adbExecTimeout'] = 50000
        capabilities['systemPort'] = system_port
        capabilities['mjpegServerPort'] = mjpeg_server_port

        self.capabilities = capabilities
        self.capabilities_options = UiAutomator2Options().load_capabilities(capabilities)

    def __enter__(self):
        self.open()

        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def open(self):
        """Used to open the appium web driver session"""

        self.driver = webdriver.Remote(APPIUM_SERVER_URL, options=self.capabilities_options)

    def close(self):
        """Closes the appium driver session"""
        if self.driver:
            if self.files_sent:
                self.cleanup_files()

            if self.capabilities['appPackage'] != 'org.proxydroid':
                self.driver.terminate_app(self.capabilities['appPackage'])
            else:
                self.driver.press_keycode(3)

            self.driver.quit()
            self.logger.debug('Driver was quit')

    def locate(self, by, locator, location_type=None):
        """Locates the first elements with the given By"""
        wait = WebDriverWait(self.driver, 10)
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
        wait = WebDriverWait(self.driver, 5)
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
            wait = WebDriverWait(self.driver, 1)
            wait.until(expected_conditions.presence_of_element_located((by, locator)))
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

            self.logger.debug(f'Sleeping for {round(duration, 2)} {word}')
            time.sleep(seconds)

    def click(self, element=None, x=None, y=None):
        if element:
            width = element.size['width']
            height = element.size['height']
            center_x = width / 2
            center_y = height / 2

            xoffset = int(center_x) - random.randint(int(center_x * .2), int(center_x * .8))
            yoffset = int(center_y) - random.randint(int(center_y * .2), int(center_y * .8))
            action = ActionChains(self.driver).move_to_element_with_offset(element, xoffset, yoffset).click()
            action.perform()
        else:
            self.driver.execute_script('mobile: clickGesture', {'x': x, 'y': y})

    def long_click(self, element, duration=1000):
        width = element.size['width']
        height = element.size['height']

        xoffset = random.randint(int(width * .2), int(width * .8))
        yoffset = random.randint(int(height * .2), int(height * .8))

        self.driver.execute_script('mobile: longClickGesture', {'x': xoffset, 'y': yoffset, 'elementId': element.id, 'duration': duration})

    def swipe(self, direction, scroll_amount, speed=1200):
        window_size = self.driver.get_window_size()
        if direction in ('up', 'down'):
            bounding_box_xpercent_min = .5
            bounding_box_xpercent_max = .9
            bounding_box_ypercent_min = .2
            bounding_box_ypercent_max = .7
        else:
            bounding_box_xpercent_min = .1
            bounding_box_xpercent_max = .9
            bounding_box_ypercent_min = .7
            bounding_box_ypercent_max = .8

        scroll_x = bounding_box_xpercent_min * window_size['width']
        scroll_y = bounding_box_ypercent_min * window_size['height']
        scroll_width = (window_size['width'] * bounding_box_xpercent_max) - (
                    window_size['width'] * bounding_box_xpercent_min)
        scroll_height = (window_size['height'] * bounding_box_ypercent_max) - (
                    window_size['height'] * bounding_box_ypercent_min)

        if direction in ('up', 'down'):
            full_scrolls = int(scroll_amount / scroll_height)
            last_scroll = round(scroll_amount / scroll_height % 1, 2)
        else:
            full_scrolls = int(scroll_amount / scroll_width)
            last_scroll = round(scroll_amount / scroll_width % 1, 2)
        scroll_percents = [1.0] * full_scrolls + [last_scroll]

        total_scroll = 0
        for index, scroll_percent in enumerate(scroll_percents):
            total_scroll += scroll_height * scroll_percent
            self.driver.execute_script('mobile: swipeGesture', {
                'left': scroll_x, 'top': scroll_y, 'width': scroll_width, 'height': scroll_height,
                'direction': direction,
                'percent': scroll_percent,
                'speed': speed
            })
            if index + 1 != len(scroll_percents):
                self.sleep(.5)

    def send_keys(self, element, text):
        char = None
        self.click(element)
        for index, line in enumerate(text.split('\n')):
            action = ActionChains(self.driver)

            if index != 0:
                self.driver.press_keycode(66)

            words = line.split(' ')
            for inner_index, word in enumerate(words):
                word = word.strip()
                try:
                    for char in word:
                        action.send_keys(char).pause(random.uniform(.1, .2))

                    if len(words) > 1 and inner_index != len(words) - 1:
                        action.send_keys(' ')

                    action.perform()
                except Exception:
                    self.logger.error(traceback.format_exc())
                    self.logger.info(word)
                    self.logger.info(char)

        self.driver.back()

    def launch_app(self, app_name, retries=0):
        self.logger.info(f'Launching app {app_name}. Attempt # {retries + 1}')

        self.logger.info('Going to home screen')

        self.driver.press_keycode(3)

        self.sleep(1)

        self.swipe('up', 1000)

        self.logger.info('Searching for app')

        search = self.locate(AppiumBy.ID, 'com.google.android.apps.nexuslauncher:id/input')
        _index = app_name.find('_')

        if _index != -1:
            search.send_keys(app_name[:_index])
        else:
            search.send_keys(app_name)

        if not self.is_present(AppiumBy.ACCESSIBILITY_ID, app_name):
            return False

        app = self.locate(AppiumBy.ACCESSIBILITY_ID, app_name)
        app.click()

        self.logger.info('App launched')

        self.sleep(2)

        return True

    def get_current_app_package(self):
        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        device = client.device(self.capabilities.get('udid'))

        windows = device.shell('dumpsys window')
        current_focus_index = windows.find('mCurrentFocus')
        end_of_current_focus = windows[current_focus_index:].find('\n')
        current_focus = windows[current_focus_index:end_of_current_focus + current_focus_index]
        divider_index = current_focus.find('/')
        space_index = current_focus.rfind(' ')

        return current_focus[space_index + 1:divider_index]

    def send_file(self, destination_path, source_path):
        self.driver.push_file(destination_path=destination_path, source_path=source_path)
        self.files_sent.append(destination_path)

    def cleanup_files(self):
        self.logger.debug('Cleaning up files')
        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        adb_device = client.device(serial=self.capabilities['udid'])
        for file_path in self.files_sent:
            adb_device.shell(f'rm {file_path}')


class PoshMarkClient(AppiumClient):
    def __init__(self, campaign: Campaign, logger, device: Device):
        self.driver = None
        self.campaign = campaign
        self.logger = logger
        self.is_registered = False
        self.listed = False
        self.account_pop_up_clicked = False
        self.posh_party_alert_dismissed = False
        self.profile_picture_added = False
        self.finished_registering = False
        self.need_alert_check = False
        self.number_of_alert_checks = 0
        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)
        self.bucket = s3_client.Bucket(settings.AWS_STORAGE_BUCKET_NAME)

        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage='com.poshmark.app',
            appActivity='com.poshmark.ui.MainActivity',
            language='en',
            locale='US',
            noReset=True
        )

        super(PoshMarkClient, self).__init__(device.serial, device.system_port, device.mjpeg_server_port, logger, capabilities)

    def locate(self, by, locator, location_type=None, retry=0):
        """Locates the first elements with the given By"""
        wait = WebDriverWait(self.driver, 2)
        try:
            if location_type:
                if location_type == 'visibility':
                    return wait.until(expected_conditions.visibility_of_element_located((by, locator)))
                elif location_type == 'clickable':
                    return wait.until(expected_conditions.element_to_be_clickable((by, locator)))
                else:
                    return None
            else:
                return wait.until(expected_conditions.presence_of_element_located((by, locator)))
        except (TimeoutException, NoSuchElementException):
            self.logger.warning(f'Element could not be found with {locator}.')

            self.alert_check()

            self.logger.info(f'Trying again to locate element by {locator}')

            if retry < 2:
                retry += 1
                return self.locate(by, locator, location_type, retry)
            else:
                if location_type:
                    if location_type == 'visibility':
                        return wait.until(expected_conditions.visibility_of_element_located((by, locator)))
                    elif location_type == 'clickable':
                        return wait.until(expected_conditions.element_to_be_clickable((by, locator)))
                    else:
                        return None
                else:
                    return wait.until(expected_conditions.presence_of_element_located((by, locator)))

    def download_and_send_file(self, key, download_folder):
        filename = key.split('/')[-1]
        download_location = f'{download_folder}/{filename}'

        if not download_location.startswith('/'):
            download_location = '/' + download_location

        self.bucket.download_file(key, download_location)
        self.send_file(destination_path=f'/sdcard/Pictures/{filename}', source_path=download_location)

    def alert_check(self):
        self.logger.info('Checking for an alert')

        if not self.posh_party_alert_dismissed and self.is_present(AppiumBy.ID, 'android:id/alertTitle'):
            title = self.locate(AppiumBy.ID, 'android:id/alertTitle').text

            if 'party' in title.lower():
                self.logger.info('Posh Party Alert found')
                cancel = self.locate(AppiumBy.ID, 'android:id/button2')
                self.logger.info(f'Clicking the {cancel.text} button')
                self.click(cancel)

                self.posh_party_alert_dismissed = True

                return True
            elif 'error' in title.lower():
                message = self.locate(AppiumBy.ID, 'android:id/message')
                self.logger.info(f'Error alert was found with message: {message.text}')
                button_1 = self.locate(AppiumBy.ID, 'android:id/button1')

                self.logger.info(f'Clicking {button_1.text} button')

                self.click(button_1)

                return True
            else:
                self.logger.info(f'No handler for alert with the following title: {title}')

        elif self.is_present(AppiumBy.ID, 'android:id/message'):
            message = self.locate(AppiumBy.ID, 'android:id/message')
            
            if 'party' in message.text.lower():
                self.logger.info('Posh Party Alert found')
                cancel = self.locate(AppiumBy.ID, 'android:id/button2')
                self.logger.info(f'Clicking the {cancel.text} button')
                self.click(cancel)

                self.posh_party_alert_dismissed = True
            else:
                self.logger.info(f'Alert with the following message popped up: {message.text}')

                self.logger.info(self.driver.page_source)

                ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
                self.logger.info(f'Clicking the {ok_button.text} button')
                self.click(ok_button)

            return True
        elif self.is_present(AppiumBy.ID, 'com.poshmark.app:id/tooltip_close_button'):
            self.logger.info('Tooltip found - Closing')
            close_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/tooltip_close_button')
            close_button.click()


        self.logger.info('No alerts found')

        return False

    def tap_img(self, name):
        search_box = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/searchbar_title')
        self.click(search_box)

        search_input = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/search_src_text')
        search_input.send_keys(name)

        self.sleep(1)

        self.driver.back()

        img = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/icon_thumb')
        img.click()

    def input_text(self, element, text, custom_send_keys=True):
        if element.text != text:
            if element.text != '':
                element.clear()

            if custom_send_keys:
                self.send_keys(element, text)
            else:
                element.send_keys(text)

    def scroll_until_found(self, by, locator, direction='down', max_scrolls=10):
        swipe_direction = 'up' if direction == 'down' else 'down'
        scroll_attempts = 0
        while not self.is_present(by, locator) and scroll_attempts < max_scrolls:
            self.logger.info(f'Could not find {locator}, scrolling...')
            self.swipe(swipe_direction, 1000)

            if scroll_attempts > int(max_scrolls / 2):
                self.alert_check()

            scroll_attempts += 1

        if scroll_attempts < max_scrolls:
            return True
        else:
            self.swipe('down', 1000, 3000)
            return False

    def register(self):
        self.logger.info('Starting Registration Process')
        campaign_folder = f'/{slugify(self.campaign.title)}'
        os.makedirs(campaign_folder, exist_ok=True)

        profile_picture_key = self.campaign.posh_user.profile_picture.name
        self.download_and_send_file(profile_picture_key, campaign_folder)

        try:
            if self.is_present(AppiumBy.ID, 'userTab'):
                self.logger.info('User is registered')
                return True

            while not self.is_registered:
                if self.need_alert_check:
                    self.need_alert_check = False
                    alert_dismissed = self.alert_check()

                    if not alert_dismissed:
                        self.number_of_alert_checks += 1
                        if self.number_of_alert_checks > 2:
                            self.driver.back()
                            self.number_of_alert_checks = 0
                    else:
                        self.number_of_alert_checks = 0

                if not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('No screen title elements, probably at init screen.')

                    if self.is_present(AppiumBy.ID, 'sign_up_option'):
                        sign_up = self.locate(AppiumBy.ID, 'sign_up_option')
                        self.click(sign_up)

                        self.logger.info('Clicked sign up button')
                    else:
                        self.need_alert_check = True
                else:
                    if not self.account_pop_up_clicked and self.is_present(AppiumBy.ID, 'com.google.android.gms:id/cancel'):
                        none_of_the_above = self.locate(AppiumBy.ID, 'com.google.android.gms:id/cancel')
                        self.click(none_of_the_above)
                        self.logger.info('Google accounts pop up. Clicked None of the above.')

                    window_title = self.locate(AppiumBy.ID, 'titleTextView')

                    if window_title:
                        self.logger.info(f'Currently at the {window_title.text} screen')

                    if window_title and window_title.text == 'Get Started':
                        first_name = self.locate(AppiumBy.ID, 'firstname')
                        last_name = self.locate(AppiumBy.ID, 'lastname')
                        email = self.locate(AppiumBy.ID, 'email')

                        self.input_text(first_name, self.campaign.posh_user.first_name)
                        self.input_text(last_name, self.campaign.posh_user.last_name)
                        self.input_text(email, self.campaign.posh_user.email, False)

                        self.logger.info('First Name, Last Name, and Email entered')

                        continue_button = self.locate(AppiumBy.ID, 'continueButton')
                        continue_button.click()

                        self.logger.info('Clicked continue button')
                    elif window_title and 'Welcome, ' in window_title.text:
                        if not self.profile_picture_added:
                            self.logger.info('Uploading profile picture')
                            picture_elem = self.locate(AppiumBy.ID, 'addPictureButton')
                            self.click(picture_elem)

                            photo_albums = self.locate(AppiumBy.ID, 'galleryTv')
                            self.click(photo_albums)

                            profile_picture_key = self.campaign.posh_user.profile_picture.name
                            profile_picture = self.locate(AppiumBy.XPATH, f'//android.widget.LinearLayout[contains(@content-desc, "{profile_picture_key.split("/")[-1]}")]/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
                            profile_picture.click()

                            self.sleep(1)

                            attempts = 0
                            while self.is_present(AppiumBy.ID, 'progressBar') and attempts < 4:
                                self.logger.info('Loading...')
                                self.sleep(5)
                                attempts += 1

                            if attempts >= 4:
                                self.logger.info('Never finished loading. Exiting')
                                return False

                            next_button = self.locate(AppiumBy.ID, 'nextButton')
                            self.click(next_button)

                            self.profile_picture_added = True
                            self.logger.info('Profile picture added')

                        username = self.locate(AppiumBy.ID, 'username')
                        password = self.locate(AppiumBy.ID, 'password')

                        self.input_text(username, self.campaign.posh_user.username, False)

                        password.clear()
                        password.send_keys(self.campaign.posh_user.password)

                        self.logger.info('Username and password entered')

                        create_button = self.locate(AppiumBy.ID, 'continueButton')
                        self.click(create_button)
                        self.need_alert_check = True

                        self.logger.info('Continue button clicked')

                        if self.is_present(AppiumBy.ID, 'popupContainer'):
                            new_username = self.locate(AppiumBy.ID, 'item')

                            self.logger.info(f'Looks like username was taken. Choosing new username: {new_username.text}')

                            self.click(new_username)

                            self.sleep(1)

                            username = self.locate(AppiumBy.ID, 'username')
                            self.campaign.posh_user.username = username.text
                            self.campaign.posh_user.save(update_fields=['username'])
                    elif window_title and window_title.text in ('Sizes', 'Complete your Profile'):
                        self.is_registered = True
                    else:
                        if window_title:
                            self.logger.info(f'No handler for screen with title {window_title.text}')
                            self.logger.debug(self.driver.page_source)
                        else:
                            self.logger.info('No handler for this title less screen')
                            self.logger.debug(self.driver.page_source)

                    # Inline form error handling
                    if self.is_present(AppiumBy.ID, 'textinput_error'):
                        error = self.locate(AppiumBy.ID, 'textinput_error')
                        self.logger.error(f'The following form error was found (Campaign will be stopped): {error.text}')

                        if 'email address is already tied to another user' in error.text or 'Please enter a valid email address' in error.text:
                            self.logger.info('Setting the user inactive since the email is taken or it is invalid.')
                            self.campaign.posh_user.is_active_in_posh = False
                            self.campaign.posh_user.save(update_fields=['is_active_in_posh'])

                        else:
                            self.logger.warning('No handler for this error')

                        return False

                    while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                        self.logger.info('Waiting to continue...')
                        self.sleep(5)

                        self.need_alert_check = True
                        self.number_of_alert_checks = 0

            return self.is_registered
        except (TimeoutException, StaleElementReferenceException, NoSuchElementException):
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return self.is_registered

    def finish_registration(self):
        try:
            self.logger.info('Finishing registration')

            while not self.is_present(AppiumBy.ID, 'sellTab'):
                if self.need_alert_check:
                    self.need_alert_check = False
                    self.number_of_alert_checks = 0
                    alert_dismissed = self.alert_check()

                    if not alert_dismissed:
                        self.number_of_alert_checks += 1
                        if self.number_of_alert_checks > 2:
                            self.driver.back()
                            self.number_of_alert_checks = 0
                    else:
                        self.number_of_alert_checks = 0

                if self.is_present(AppiumBy.ID, 'titleTextView'):
                    window_title = self.locate(AppiumBy.ID, 'titleTextView')
                    self.logger.info(f'Currently at the {window_title.text} screen')
                else:
                    window_title = None
                    self.logger.warning('Screen title could not be found')

                if window_title and window_title.text in ('Sizes', 'Complete your Profile'):
                    if self.is_present(AppiumBy.ID, 'continueButton'):
                        dress_size_id = 'clothingSize'
                        shoe_size_id = 'shoeSize'
                        zipcode_id = 'zip_code'
                        continue_button_id = 'continueButton'
                    else:
                        dress_size_id = 'sizeSpinnerText_II_InputLayout'
                        shoe_size_id = 'sizeSpinnerText_I'
                        zipcode_id = 'zip'
                        continue_button_id = 'nextButton'

                    self.logger.info('Putting in sizes and zip')

                    while not self.is_present(AppiumBy.ACCESSIBILITY_ID, '00'):
                        dress_size = self.locate(AppiumBy.ID, dress_size_id)
                        self.click(dress_size)
                        self.sleep(.5)

                    size_choice = random.choice(['00', '0', '2', '4', '6', '8', '10'])

                    while self.is_present(AppiumBy.ACCESSIBILITY_ID, size_choice):
                        size = self.locate(AppiumBy.ACCESSIBILITY_ID, size_choice)
                        self.click(size)
                        self.logger.info('Dress size clicked')
                        self.sleep(.5)

                    while not self.is_present(AppiumBy.ACCESSIBILITY_ID, '5'):
                        shoe_size = self.locate(AppiumBy.ID, shoe_size_id)
                        self.click(shoe_size)
                        self.sleep(.5)

                    size_choice = random.choice(['5', '5.5', '6', '6.5', '7', '7.5', '8', '8.5'])

                    while self.is_present(AppiumBy.ACCESSIBILITY_ID, size_choice):
                        size = self.locate(AppiumBy.ACCESSIBILITY_ID, size_choice)
                        self.click(size)
                        self.logger.info('Shoe size clicked')
                        self.sleep(.5)

                    zip_input = self.locate(AppiumBy.ID, zipcode_id)

                    self.input_text(zip_input, self.campaign.posh_user.postcode, False)

                    self.logger.info('Zipcode inserted')

                    continue_button = self.locate(AppiumBy.ID, continue_button_id)
                    self.click(continue_button)
                elif window_title and window_title.text in ('Follow Brands', 'Brands'):
                    self.logger.info('Selecting brands')
                    if self.is_present(AppiumBy.ID, 'brandLogo'):
                        brands = self.locate_all(AppiumBy.ID, 'brandLogo')[:9]
                    else:
                        brands = self.locate_all(AppiumBy.ID, 'suggestedBrandLogo3')[:9]

                    for brand in random.choices(brands, k=random.randint(1, 6)):
                        self.click(brand)

                    if self.is_present(AppiumBy.ID, 'continueButton'):
                        continue_button = self.locate(AppiumBy.ID, 'continueButton')
                    else:
                        continue_button = self.locate(AppiumBy.ID, 'nextButton')

                    if continue_button:
                        self.click(continue_button)
                    self.logger.info('Brands selected')
                elif window_title and window_title.text in ('Find Your Friends', 'Community'):
                    done_button = self.locate(AppiumBy.ID, 'nextButton')
                    self.click(done_button)
                    self.logger.info('Clicked on next button')
                else:
                    if window_title:
                        self.logger.info(f'No handler for screen with title {window_title.text}')
                        self.logger.debug(self.driver.page_source)
                    else:
                        self.logger.info('No handler for this title less screen')
                        self.logger.debug(self.driver.page_source)

                        self.need_alert_check = True

                while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('Waiting to continue...')
                    self.sleep(3)

                    self.need_alert_check = True
                    self.number_of_alert_checks = 0

            return True
        except (TimeoutException, StaleElementReferenceException, NoSuchElementException):
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False

    def list_item(self, item_to_list: ListedItem, listing_images: List[ListingImage]):
        try:
            listing = item_to_list.listing
            self.logger.info(f'Listing {listing.title} for {self.campaign.posh_user.username}')
            self.listed = False
            new_listing = False
            added_media_items = False
            added_title = False
            added_description = False
            added_category = False
            added_size = False
            added_brand = False
            added_original_price = False
            added_listing_price = False

            campaign_folder = f'/{slugify(self.campaign.title)}'
            listing_folder = f'{campaign_folder}/{slugify(listing.title)}'

            os.makedirs(listing_folder, exist_ok=True)

            while not self.listed:
                if self.is_present(AppiumBy.ID, 'sellTab'):
                    self.logger.info('Downloading cover photo')
                    cover_photo_key = listing.cover_photo.name
                    self.download_and_send_file(cover_photo_key, listing_folder)

                    listing_images.reverse()

                    self.logger.info('At main screen')

                    sell_button = self.locate(AppiumBy.ID, 'sellTab')
                    self.click(sell_button)

                    self.logger.info('Sell button clicked. Uploading cover photo')

                    self.sleep(1)

                    if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
                        deny_button = self.locate(AppiumBy.ID,
                                                  'com.android.permissioncontroller:id/permission_deny_button')
                        self.click(deny_button)
                        self.logger.info('Denying access to camera')

                    gallery_button = self.locate(AppiumBy.ID, 'gallery')
                    self.click(gallery_button)

                    self.logger.info('Gallery button clicked')

                    if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button'):
                        allow_button = self.locate(AppiumBy.ID,
                                                   'com.android.permissioncontroller:id/permission_allow_button')
                        self.click(allow_button)
                        self.logger.info('Allowing access to gallery')

                    self.sleep(2)
                    self.tap_img(cover_photo_key.split("/")[-1])

                    self.logger.info('Cover photo tapped')

                    next_button = self.locate(AppiumBy.ID, 'nextButton')
                    self.click(next_button)

                    self.logger.info('Next button clicked')
                    self.sleep(1)

                    next_button = self.locate(AppiumBy.ID, 'nextButton')
                    self.click(next_button)

                    self.logger.info('Next button clicked')

                    new_listing = True
                else:
                    if self.is_present(AppiumBy.ID, 'titleTextView'):
                        window_title = self.locate(AppiumBy.ID, 'titleTextView')
                    else:
                        window_title = None

                    if window_title and window_title.text == 'Listing Details':
                        if not added_media_items and len(listing_images) > 0:
                            self.logger.info('Downloading and sending listing images')
                            added_images_found = True
                            if not new_listing:
                                added_images_found = self.scroll_until_found(AppiumBy.XPATH, f"//*[contains(@text, 'PHOTOS & VIDEO')]", direction='up')
                                if added_images_found:
                                    added_images = self.locate_all(AppiumBy.ID, 'container')
                                    listing_images = listing_images[len(added_images) - 2:]

                            if added_images_found:
                                if listing_images:
                                    for listing_image in listing_images:
                                        image_key = listing_image.image.name
                                        self.download_and_send_file(image_key, listing_folder)

                                    self.sleep(5)

                                    add_more_button = self.locate(AppiumBy.ID, 'add_more')
                                    self.click(add_more_button)

                                    self.logger.info('Clicked add more button')

                                    if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button'):
                                        deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button')
                                        self.click(deny_button)

                                        self.logger.info('Denied access to camera permanently')

                                    if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
                                        deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
                                        self.click(deny_button)

                                        self.logger.info('Denied access to microphone')

                                    gallery_button = self.locate(AppiumBy.ID, 'gallery')
                                    self.click(gallery_button)

                                    self.logger.info('Clicked gallery button')

                                    self.sleep(1)

                                    group_num = 0
                                    self.swipe('up', 530)
                                    self.sleep(.75)
                                    counter = 0
                                    while counter < len(listing_images):
                                        try:
                                            img = self.locate(AppiumBy.XPATH, "//android.widget.ImageView[@resource-id='com.google.android.documentsui:id/icon_thumb' and @selected='false']")
                                            if counter == 0:
                                                self.long_click(img)
                                            else:
                                                img.click()
                                        except (TimeoutException, NoSuchElementException):
                                            self.logger.warning(f'Could not find another image')

                                        if counter != 0 and counter % 5 == 0 and counter != len(listing_images) - 1:
                                            self.swipe('up', 580 * 3)
                                            group_num += 5 if not group_num else 7
                                            self.sleep(.75)

                                        counter += 1

                                    select_button = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/action_menu_select')
                                    self.click(select_button)

                                    self.logger.info('All images selected')

                                    self.sleep(1)

                                    if self.is_present(AppiumBy.ID, 'nextButton'):
                                        next_button = self.locate(AppiumBy.ID, 'nextButton')
                                        self.click(next_button)
                                    else:
                                        self.click(element=None, x=500, y=500)

                                        next_button = self.locate(AppiumBy.ID, 'nextButton')
                                        self.click(next_button)

                                    self.logger.info('Listing images uploaded')
                                else:
                                    self.logger.info('All listing images seem to be in there already. Skipping...')

                                added_media_items = True
                            else:
                                self.logger.info('Listing images were not sent because could not check if there were any previously uploaded')

                        if not added_title:
                            title_input = self.locate(AppiumBy.ID, 'title_edit_text')
                            self.input_text(title_input, listing.title)

                            added_title = True

                        if not added_description:
                            self.logger.info('Adding description')
                            description_body = self.locate(AppiumBy.ID, 'description_body')

                            if 'required' in description_body.text.lower():
                                self.click(description_body)

                                description_input = self.locate(AppiumBy.ID, 'description_editor')
                                description_input.clear()
                                self.send_keys(description_input, str(listing.description))

                                done_button = self.locate(AppiumBy.ID, 'nextButton')
                                self.click(done_button)
                                self.logger.info('Description added')
                            else:
                                self.logger.info('Description has already been added. Skipping...')

                            added_description = True

                        if not added_category:
                            self.logger.info('Selecting category for the listing')
                            added_category_found = self.scroll_until_found(AppiumBy.ID, 'catalog_edit_text')
                            if added_category_found:
                                category = self.locate(AppiumBy.ID, 'catalog_edit_text')

                                if 'required' in category.text.lower():
                                    listing_category = listing.category
                                    space_index = listing_category.find(' ')
                                    primary_category = listing_category[:space_index].replace(' ', '_').lower()
                                    secondary_category = listing_category[space_index + 1:].replace(' ', '_').lower()
                                    subcategory = listing.subcategory.replace(' ', '_').lower()

                                    self.click(category)

                                    self.sleep(1)

                                    primary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, primary_category.lower())
                                    self.click(primary_category_button)

                                    self.sleep(1)

                                    secondary_category_clicked = False
                                    secondary_category_click_attempts = 0
                                    while not secondary_category_clicked and secondary_category_click_attempts < 7:
                                        if self.is_present(AppiumBy.ACCESSIBILITY_ID, secondary_category):
                                            secondary_category_click_attempts += 1
                                            secondary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, secondary_category)
                                            self.click(secondary_category_button)
                                            self.logger.info('Category clicked')
                                            self.sleep(.5)
                                            secondary_category_clicked = True
                                        else:
                                            self.swipe('up', 400)
                                            self.sleep(.5)

                                        secondary_category_click_attempts += 1

                                    if secondary_category_click_attempts >= 7 and not secondary_category_clicked:
                                        return False

                                    subcategory_clicked = False
                                    subcategory_click_attempts = 0
                                    while not subcategory_clicked and subcategory_click_attempts < 7:
                                        subcategory_click_attempts += 1
                                        if self.is_present(AppiumBy.ACCESSIBILITY_ID, subcategory):
                                            subcategory_button = self.locate(AppiumBy.ACCESSIBILITY_ID, subcategory)
                                            self.click(subcategory_button)
                                            self.logger.info('Clicked sub category')
                                            self.sleep(.5)
                                            subcategory_clicked = True
                                        else:
                                            self.swipe('up', 400)
                                            self.sleep(.5)

                                        subcategory_click_attempts += 1

                                    if subcategory_click_attempts >= 7 and not secondary_category_clicked:
                                        return False

                                    done_button = self.locate(AppiumBy.ID, 'nextButton')
                                    self.click(done_button)

                                    self.logger.info('Clicked done button')
                                else:
                                    self.logger.info('Category has already been selected')

                                added_category = True

                        while not self.is_present(AppiumBy.ID, 'titleTextView') or self.locate(AppiumBy.ID, 'titleTextView').text != 'Listing Details':
                            for _ in range(3):
                                self.driver.back()
                                self.sleep(.2)

                        if not added_size:
                            self.logger.info('Putting in size')

                            size_input_found = self.scroll_until_found(AppiumBy.ID, 'size_edit_text')

                            if size_input_found:
                                added_size = False
                                size_button = self.locate(AppiumBy.ID, 'size_edit_text')
                                if 'required' in size_button.text.lower():
                                    self.click(size_button)

                                    if listing.size.lower() == 'os':
                                        one_size = self.locate(AppiumBy.ACCESSIBILITY_ID, 'One Size')
                                        self.click(one_size)
                                        added_size = True
                                        self.logger.info('Clicked one size')
                                    else:
                                        if 'belt' not in listing.category.lower() + listing.subcategory.lower():
                                            package_name = self.capabilities['appPackage']
                                            selected_size_category = self.locate(AppiumBy.XPATH, f"//android.widget.TextView[@resource-id='{package_name}:id/size_tab_title_text' and @selected='true']")
                                            while self.is_present(AppiumBy.XPATH, f"//android.widget.TextView[@resource-id='{package_name}:id/size_tab_title_text' and @selected='true']") and selected_size_category.text != 'CUSTOM':
                                                self.logger.info(f'Looking for size in {selected_size_category.text} category')
                                                size_found = self.scroll_until_found(AppiumBy.ACCESSIBILITY_ID, listing.size, max_scrolls=4)
                                                if size_found:
                                                    size = self.locate(AppiumBy.ACCESSIBILITY_ID, listing.size)
                                                    self.click(size)

                                                    added_size = True
                                                else:
                                                    self.swipe('left', 250)
                                                    selected_size_category = self.locate(AppiumBy.XPATH, f"//android.widget.TextView[@resource-id='{package_name}:id/size_tab_title_text' and @selected='true']")

                                        if not added_size:
                                            custom_size_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Custom')
                                            self.click(custom_size_button)

                                            add_option = self.locate(AppiumBy.ID, 'container')
                                            self.click(add_option)

                                            custom_size_input = self.locate(AppiumBy.ID, 'messageText')
                                            custom_size_input.send_keys(listing.size)

                                            next_button = self.locate(AppiumBy.ID, 'nextButton')
                                            self.click(next_button)

                                            self.logger.info(f'Put in {listing.size} for the size')

                                            added_size = True

                        while not self.is_present(AppiumBy.ID, 'titleTextView') or self.locate(AppiumBy.ID, 'titleTextView').text != 'Listing Details':
                            for _ in range(3):
                                self.driver.back()
                                self.sleep(.2)

                        if not added_brand and listing.brand:
                            self.logger.info('Putting in brand')

                            brand_edit_found = self.scroll_until_found(AppiumBy.ID, 'brand_edit_text')

                            if brand_edit_found:
                                brand_input = self.locate(AppiumBy.ID, 'brand_edit_text')
                                while brand_edit_found and brand_input.text.lower() != listing.brand.lower():
                                    self.click(brand_input)
                                    self.logger.info('Clicked brand button')

                                    brand_search = self.locate(AppiumBy.ID, 'searchTextView')
                                    brand_search.send_keys(listing.brand.lower())

                                    self.sleep(1)
                                    brand_selector = listing.brand.lower()
                                    brand_xpath = f'//*[translate(@content-desc, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz") = "{brand_selector}"]'
                                    if not self.is_present(AppiumBy.XPATH, brand_xpath):
                                        self.logger.info('Brand did not pop up on search... Taping back.')
                                    else:
                                        brand = self.locate(AppiumBy.XPATH, brand_xpath)
                                        self.click(brand)

                                        self.logger.info('Clicked brand')

                                    while not self.is_present(AppiumBy.ID, 'titleTextView') or self.locate(AppiumBy.ID, 'titleTextView').text != 'Listing Details':
                                        self.driver.back()
                                        self.sleep(.2)

                                    brand_edit_found = self.scroll_until_found(AppiumBy.ID, 'brand_edit_text')

                                    if brand_edit_found:
                                        brand_input = self.locate(AppiumBy.ID, 'brand_edit_text')
                                    else:
                                        brand_input = None
                                added_brand = brand_edit_found and brand_input.text.lower() == listing.brand.lower()
                                self.logger.info('Brand inputted')

                        if not added_original_price:
                            original_price_found = self.scroll_until_found(AppiumBy.ID, 'original_price_edit_text')

                            if original_price_found:
                                original_price = self.locate(AppiumBy.ID, 'original_price_edit_text')
                                self.input_text(original_price, str(listing.original_price))

                                added_original_price = True

                        if not added_listing_price:
                            listing_price_found = self.scroll_until_found(AppiumBy.ID, 'listing_price_edit_text')

                            if listing_price_found:
                                listing_price = self.locate(AppiumBy.ID, 'listing_price_edit_text')
                                self.input_text(listing_price, str(listing.listing_price))

                                added_listing_price = True

                            earnings_str = self.locate(AppiumBy.ID, 'earnings_edit_text').text
                            earnings = Decimal(earnings_str.replace('$', ''))

                            item_to_list.earnings = earnings
                            item_to_list.save()

                        next_button = self.locate(AppiumBy.ID, 'nextButton')
                        self.click(next_button)
                    elif window_title and window_title.text == 'Share Listing':
                        list_button = self.locate(AppiumBy.ID, 'nextButton')
                        self.click(list_button)

                        list_attempts = 0
                        sleep_amount = 10
                        self.logger.info('Sell button clicked')
                        self.sleep(5)
                        sell_button_present = self.is_present(AppiumBy.ID, 'sellTab')

                        while not sell_button_present and list_attempts < 20:
                            sell_button_present = self.is_present(AppiumBy.ID, 'sellTab')
                            list_attempts += 1

                            if self.is_present(AppiumBy.ID, 'android:id/message'):
                                error_message = self.locate(AppiumBy.ID, 'android:id/message')
                                self.logger.warning(f'A pop up came up with the following message: {error_message.text}')

                                if 'you cannot currently perform this request' in error_message.text.lower():
                                    self.logger.info('User is inactive and cannot list items. Setting inactive...')
                                    self.campaign.posh_user.is_active_in_posh = False
                                    self.campaign.posh_user.save(update_fields=['is_active_in_posh'])

                                    return False
                                else:
                                    retry_button = self.locate(AppiumBy.ID, 'android:id/button1')
                                    self.click(retry_button)
                                    self.logger.info(self.driver.page_source)
                                    self.logger.info('Clicked button 1')

                                self.sleep(5)

                                list_attempts = 0
                                sleep_amount = 20
                            elif self.is_present(AppiumBy.XPATH, f"//*[contains(@text, 'Certify Listing')]"):
                                self.logger.warning('Certify listing page came up. Clicking certify.')
                                certify_button = self.locate(AppiumBy.XPATH, f"//*[contains(@text, 'Certify Listing')]")
                                self.click(certify_button)

                                self.sleep(.5)
                                certify_ok = self.locate(AppiumBy.ID, 'android:id/button1')
                                self.click(certify_ok)

                                list_attempts = 0
                            elif self.is_present(AppiumBy.ID, 'com.poshmark.app:id/close'):
                                close_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/close')
                                close_button.click()
                            else:
                                self.logger.info('Item not listed yet')
                                self.sleep(sleep_amount)
                        else:
                            if list_attempts >= 10:
                                self.logger.error(
                                    f'Attempted to locate the sell button {list_attempts} times but could not find it.')
                                return False
                            else:
                                self.logger.info('Item listed successfully')

                        self.listed = True
                    elif window_title or self.is_present(AppiumBy.ID, 'actionbar_closet_layout') or self.is_present(AppiumBy.ID, 'actionbarTitleLayout') or self.is_present(AppiumBy.ID, 'select_a_brand_title'):
                        for _ in range(3):
                            self.driver.back()
                            self.sleep(.2)
                    elif self.is_present(AppiumBy.ID, 'design_bottom_sheet'):
                        self.driver.back()
                    elif self.is_present(AppiumBy.XPATH, "//*[starts-with(@resource-id, 'com.google.android.documentsui:id')]"):
                        self.logger.info('On document screen, going back.')
                        self.driver.back()
                        self.driver.back()
                    elif self.is_present(AppiumBy.ID, 'gallery'):
                        self.logger.info('On gallery screen, going back')
                        self.driver.back()
                    else:
                        self.logger.info('Window title element not found.')

                        self.alert_check()

            return self.listed

        except (TimeoutException, StaleElementReferenceException, NoSuchElementException):
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return self.listed

    def get_listed_item_id(self):
        response = None
        soup = None
        a_tag = None
        try:
            user_tab = self.locate(AppiumBy.ID, 'userTab')
            self.click(user_tab)

            self.sleep(1)

            if self.is_present(AppiumBy.ACCESSIBILITY_ID, 'myClosetMenuButton'):
                my_closet = self.locate(AppiumBy.ACCESSIBILITY_ID, 'myClosetMenuButton')
                self.click(my_closet)

            first_share_button = self.locate(AppiumBy.XPATH, f"//*[@resource-id='{self.capabilities['appPackage']}:id/shareButton']")
            self.click(first_share_button)

            copy_link_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'copyButton')
            self.click(copy_link_button)

            self.sleep(1)

            short_link = self.driver.get_clipboard_text()

            response = requests.get(short_link)

            soup = BeautifulSoup(response.text, "html.parser")
            a_tag = soup.find("a", {"class": "secondary-action"})
            listing_url = a_tag["href"]

            self.driver.back()

            return listing_url.split("/")[-1].split("?")[0]
        except Exception as e:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)
            self.logger.debug(str(soup))
            self.logger.debug(str(response))
            self.logger.debug(str(a_tag))

            return ''


class ProxyDroidClient(AppiumClient):
    def __init__(self, device: Device, logger, proxy: Proxy):
        self.proxy = proxy

        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage='org.proxydroid',
            appActivity='org.proxydroid.ProxyDroid',
            language='en',
            locale='US',
            noReset=True,
        )
        super(ProxyDroidClient, self).__init__(device.serial, device.system_port, device.mjpeg_server_port, logger, capabilities)

    def set_proxy(self):
        self.swipe('down', 1000, 2000)
        values_to_check = {
            'Host': self.proxy.hostname,
            'Port': self.proxy.port,
            'User': self.proxy.username,
            'Password': self.proxy.password
        }
        values_checked = []

        proxy_switch = self.locate(AppiumBy.ID, 'android:id/switch_widget')
        if proxy_switch.get_attribute('checked') == 'true':
            proxy_switch.click()

        while any(elem not in values_checked for elem in values_to_check.keys()):
            containers = self.locate_all(AppiumBy.CLASS_NAME, 'android.widget.LinearLayout')

            for container in containers:
                try:
                    title_element = container.find_element(AppiumBy.ID, 'android:id/title')
                    summary_element = container.find_element(AppiumBy.ID, 'android:id/summary')
                    current_title = title_element.text

                    if current_title in values_to_check.keys() and current_title not in values_checked and summary_element.text != \
                            values_to_check[current_title]:
                        title_element.click()

                        text_box = self.locate(AppiumBy.ID, 'android:id/edit')
                        text_box.clear()
                        text_box.send_keys(values_to_check[current_title])

                        ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
                        ok_button.click()

                        self.sleep(1)

                    values_checked.append(current_title)

                except (TimeoutException, NoSuchElementException):
                    pass
            self.swipe('up', 1000)

        self.swipe('down', 1500, 2000)
        proxy_switch = self.locate(AppiumBy.ID, 'android:id/switch_widget')
        proxy_switch.click()

        self.sleep(5)


class AndroidFakerClient(AppiumClient):
    def __init__(self, device: Device, logger):
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage='com.android1500.androidfaker',
            appActivity='.ui.activity.MainActivity',
            language='en',
            locale='US',
            noReset=True,
        )
        super(AndroidFakerClient, self).__init__(device.serial, device.system_port, device.mjpeg_server_port, logger, capabilities)

    def enable_faker(self):
        more_options = self.locate(AppiumBy.ACCESSIBILITY_ID, 'More options')
        more_options.click()

        fast_reboot = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ListView/android.widget.LinearLayout[1]/android.widget.LinearLayout')
        fast_reboot.click()

    def set_value(self, value):
        value_box = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/edt_values')

        if value_box.text != value:
            value_box.clear()
            value_box.send_keys(value)

        save_button = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/save')
        save_button.click()

        self.sleep(.5)

    def set_faker_values(self, faker_values):
        field_mappings = {
            'wifi_mac': 'com.android1500.androidfaker:id/edt_wifimac',
            'wifi_ssid': 'com.android1500.androidfaker:id/edt_wifiSsid',
            'wifi_bssid': 'com.android1500.androidfaker:id/edt_wifiBssid',
            'bluetooth_id': 'com.android1500.androidfaker:id/edt_bt',
            'sim_sub_id': 'com.android1500.androidfaker:id/edt_simSub',
            'sim_serial': 'com.android1500.androidfaker:id/edt_simSerial',
            'android_id': 'com.android1500.androidfaker:id/edt_id',
            'mobile_number': 'com.android1500.androidfaker:id/edt_mobno',
            'hw_serial': 'com.android1500.androidfaker:id/edt_hw',
            'ads_id': 'com.android1500.androidfaker:id/edt_ads',
            'gsf': 'com.android1500.androidfaker:id/edt_gsf',
            'media_drm': 'com.android1500.androidfaker:id/edt_drm',
        }

        if not self.is_present(AppiumBy.ID, 'com.android1500.androidfaker:id/edt_imei'):
            self.swipe('up', 4000, 6000)

        edit_imei = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/edt_imei')
        edit_imei.click()

        imei1 = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/edt_imei_1')
        imei1.clear()
        imei1.send_keys(faker_values['imei1'])

        imei2 = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/edt_imei_2')
        imei2.clear()
        imei2.send_keys(faker_values['imei2'])

        save_imei = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/save_imei')
        save_imei.click()

        self.sleep(.5)

        for name, value_id in field_mappings.items():
            while not self.is_present(AppiumBy.ID, value_id):
                self.swipe('up', 1000)

            edit_button = self.locate(AppiumBy.ID, value_id)
            edit_button.click()

            self.set_value(faker_values[name])

        self.enable_faker()

    def get_faker_values(self):
        field_mappings = {
            'imei1': 'com.android1500.androidfaker:id/tvImei',
            'imei2': 'com.android1500.androidfaker:id/tvImei2',
            'wifi_mac': 'com.android1500.androidfaker:id/tvWifi',
            'wifi_ssid': 'com.android1500.androidfaker:id/tvWifiSsid',
            'wifi_bssid': 'com.android1500.androidfaker:id/tvbssid',
            'bluetooth_id': 'com.android1500.androidfaker:id/tvBmac',
            'sim_sub_id': 'com.android1500.androidfaker:id/tvSimSub',
            'sim_serial': 'com.android1500.androidfaker:id/tvSimSerial',
            'android_id': 'com.android1500.androidfaker:id/tvId',
            'mobile_number': 'com.android1500.androidfaker:id/tvMobNo',
            'hw_serial': 'com.android1500.androidfaker:id/tvHSerial',
            'ads_id': 'com.android1500.androidfaker:id/tvADV',
            'gsf': 'com.android1500.androidfaker:id/tvGSF',
            'media_drm': 'com.android1500.androidfaker:id/tvDrm',
        }
        faker_values = {}

        self.swipe('up', 4000, 6000)

        sim_operator_toggle = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/switchSimOperator')

        if sim_operator_toggle.get_attribute('checked') == 'true':
            sim_operator_toggle.click()

        self.swipe('down', 4000, 6000)

        random_all_button = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/rnd_all')
        random_all_button.click()

        self.sleep(1)

        for name, value_id in field_mappings.items():
            while not self.is_present(AppiumBy.ID, value_id):
                self.swipe('up', 1000)

            needed_value = self.locate(AppiumBy.ID, value_id)
            faker_values[name] = needed_value.text

        sim_operator_toggle = self.locate(AppiumBy.ID, 'com.android1500.androidfaker:id/switchSimOperator')

        if sim_operator_toggle.get_attribute('checked') == 'false':
            sim_operator_toggle.click()

        self.enable_faker()

        return faker_values


class SwiftBackupClient(AppiumClient):
    def __init__(self, device: Device, logger, posh_user: PoshUser):
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage='org.swiftapps.swiftbackup',
            appActivity='.intro.IntroActivity',
            language='en',
            locale='US',
            noReset=True,
        )

        self.posh_user = posh_user

        self.location = f'/backups/{posh_user.username}'
        os.makedirs(self.location, exist_ok=True)

        super(SwiftBackupClient, self).__init__(device.serial, device.system_port, device.mjpeg_server_port, logger, capabilities)

    def reset_data(self):
        app_button = self.locate(AppiumBy.XPATH,
                                 '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.RelativeLayout/android.widget.ScrollView/androidx.viewpager.widget.b/android.widget.ScrollView/android.widget.LinearLayout/androidx.cardview.widget.CardView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[1]')
        app_button.click()

        search_icon = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/action_search')
        search_icon.click()

        search_bar = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/searchEditText')
        search_bar.send_keys('poshmark')

        app = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/container')
        app.click()

        self.sleep(.5)

        iv_menu = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/iv_menu')
        iv_menu.click()

        reset_data = self.locate(AppiumBy.XPATH,
                                 '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ScrollView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView[1]/android.widget.Button[3]')
        reset_data.click()

        yes_button = self.locate(AppiumBy.ID, 'android:id/button1')
        yes_button.click()

    def _download_backup_files(self):
        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)
        bucket = s3_client.Bucket(settings.AWS_STORAGE_BUCKET_NAME)

        app_data: AppData = AppData.objects.filter(posh_user=self.posh_user)

        bucket.download_file(app_data.backup_data.name, f'{self.location}/com.poshmark.app.dat')
        bucket.download_file(app_data.xml_data.name, f'{self.location}/com.poshmark.app.xml')

    def save_backup(self):
        app_button = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.RelativeLayout/android.widget.ScrollView/androidx.viewpager.widget.b/android.widget.ScrollView/android.widget.LinearLayout/androidx.cardview.widget.CardView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[1]')
        app_button.click()

        search_icon = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/action_search')
        search_icon.click()

        search_bar = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/searchEditText')
        search_bar.send_keys('poshmark')

        app = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/container')
        app.click()

        self.sleep(.5)

        # Create backup
        data_button = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.ScrollView/android.widget.LinearLayout/androidx.cardview.widget.CardView[1]/android.view.ViewGroup/android.widget.FrameLayout/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView/androidx.cardview.widget.CardView[2]/android.view.ViewGroup')
        data_button.click()

        backup_to_device = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ListView/android.widget.LinearLayout[1]/android.widget.LinearLayout')
        backup_to_device.click()

        while not self.is_present(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/tv_progress_message') or self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/tv_progress_message').text != 'Done':
            self.sleep(1)

        done_button = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/btn_action')
        done_button.click()

        self.sleep(.5)

        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        device = client.device(self.capabilities.get('udid'))

        device.pull('/storage/emulated/0/SwiftBackup/accounts/8690a48a4fcc72f1/backups/apps/local/com.poshmark.app.dat', f'{self.location}/com.poshmark.app.dat')
        device.pull('/storage/emulated/0/SwiftBackup/accounts/8690a48a4fcc72f1/backups/apps/local/com.poshmark.app.xml', f'{self.location}/com.poshmark.app.xml')

        if AppData.objects.filter(posh_user=self.posh_user).exists():
            app_data: AppData = AppData.objects.filter(posh_user=self.posh_user).first()

            with open(f'{self.location}/com.poshmark.app.dat', 'rb') as data_file:
                app_data.backup_data.save('com.poshmark.app.dat', File(data_file))

            with open(f'{self.location}/com.poshmark.app.xml', 'rb') as xml_file:
                app_data.xml_data.save('com.poshmark.app.xml', File(xml_file))

            app_data.save()
        else:
            # Create a new AppData instance and save it
            with open(f'{self.location}/com.poshmark.app.dat', 'rb') as data_file:
                with open(f'{self.location}/com.poshmark.app.xml', 'rb') as xml_file:
                    AppData.objects.create(
                        posh_user=self.posh_user,
                        backup_data=File(data_file),
                        xml_data=File(xml_file),
                        type=AppData.POSHMARK
                    )

        # Delete backup
        more_info = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.ScrollView/android.widget.LinearLayout/androidx.cardview.widget.CardView[2]/android.widget.LinearLayout/android.view.ViewGroup/android.view.ViewGroup/android.widget.ImageView')
        more_info.click()

        delete_backup = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ListView/android.widget.LinearLayout[2]/android.widget.LinearLayout')
        delete_backup.click()

        yes_button = self.locate(AppiumBy.ID, 'android:id/button1')
        yes_button.click()

        iv_menu = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/iv_menu')
        iv_menu.click()

        reset_data = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ScrollView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView[1]/android.widget.Button[3]')
        reset_data.click()

        yes_button = self.locate(AppiumBy.ID, 'android:id/button1')
        yes_button.click()

    def load_backup(self):
        self._download_backup_files()

        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        device = client.device(self.capabilities.get('udid'))

        device.push(f'{self.location}/com.poshmark.app.dat', '/storage/emulated/0/SwiftBackup/accounts/8690a48a4fcc72f1/backups/apps/local/com.poshmark.app.dat')
        device.push(f'{self.location}/com.poshmark.app.xml', '/storage/emulated/0/SwiftBackup/accounts/8690a48a4fcc72f1/backups/apps/local/com.poshmark.app.xml')

        app_button = self.locate(AppiumBy.XPATH,
                                 '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.RelativeLayout/android.widget.ScrollView/androidx.viewpager.widget.b/android.widget.ScrollView/android.widget.LinearLayout/androidx.cardview.widget.CardView/android.widget.LinearLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[1]')
        app_button.click()

        search_icon = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/action_search')
        search_icon.click()

        search_bar = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/searchEditText')
        search_bar.send_keys('poshmark')

        app = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/container')
        app.click()

        self.sleep(.5)

        # Restore backup
        restore_button = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/btn_restore')
        restore_button.click()

        confirm_button = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/btn_action')
        confirm_button.click()

        while not self.is_present(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/tv_progress_message') or self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/tv_progress_message').text != 'Done':
            self.sleep(1)

        done_button = self.locate(AppiumBy.ID, 'org.swiftapps.swiftbackup:id/btn_action')
        done_button.click()
