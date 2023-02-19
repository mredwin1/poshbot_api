import boto3
import os
import random
import requests
import time
import traceback

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from django.conf import settings
from ppadb.client import Client as AdbClient
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException, InvalidArgumentException
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from typing import List

from core.models import Campaign, Listing, ListingImage

APPIUM_SERVER_URL = f'http://{os.environ.get("LOCAL_SERVER_IP")}:4723'


class AppiumClient:
    def __init__(self, device_serial, logger, capabilities):
        self.driver = None
        self.logger = logger

        capabilities['udid'] = device_serial
        capabilities['adbExecTimeout'] = 50000
        self.capabilities = capabilities

    def __enter__(self):
        self.open()

        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def open(self):
        """Used to open the appium web driver session"""
        self.driver = webdriver.Remote(APPIUM_SERVER_URL, self.capabilities)

    def close(self):
        """Closes the appium driver session"""
        if self.driver:
            self.driver.quit()

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
            wait = WebDriverWait(self.driver, 5)
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

            self.logger.info(f'Sleeping for about {round(duration, 2)} {word}')
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

    def long_click(self, element, duration=500):
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
            bounding_box_ypercent_min = .1
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

        full_scrolls = int(scroll_amount / scroll_height)
        last_scroll = round(scroll_amount / scroll_height % 1, 2)
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

    def launch_app(self, app_name):
        self.driver.press_keycode(3)

        self.sleep(1)

        self.swipe('up', 1000)

        search = self.locate(AppiumBy.ID, 'com.google.android.apps.nexuslauncher:id/input')
        _index = app_name.find('_')

        if _index != -1:
            search.send_keys(app_name[:_index])
        else:
            search.send_keys(app_name)

        app = self.locate(AppiumBy.ACCESSIBILITY_ID, app_name)
        app.click()

    def get_current_app_package(self):
        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        device = client.device(self.capabilities.get('udid'))

        windows = device.shell('dumpsys window windows')
        app_package_index = windows.find('com.poshmark.')

        return windows[app_package_index:app_package_index + 16]


class PoshMarkClient(AppiumClient):
    def __init__(self, device_serial, campaign: Campaign, logger, app_package='com.poshmark.app'):
        self.driver = None
        self.campaign = campaign
        self.logger = logger
        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)
        self.bucket = s3_client.Bucket(settings.AWS_STORAGE_BUCKET_NAME)
        self.zipcodes = [33101, 33109, 33125, 33126, 33127, 33128, 33129, 33130, 33131, 33132, 33133, 33134, 33135, 33136, 33137, 33138, 33139, 33142, 33144, 33145, 33146, 33147, 33149, 32789, 32801, 32802, 32803, 32804, 32805, 32806, 32807, 32808, 32809, 32810, 32811, 32812, 32814, 32819, 32821, 32822, 32824, 32827, 32829, 32832, 32834, 32835, 32839, 32853, 32854, 32855, 32856, 32861, 32862, 32878, 32885, 32886, 32891, 32897, 32114, 32117, 32118, 32119, 32124, 32129, 32174, 33109, 33132, 33139, 33140, 33141, 33559, 33602, 33603, 33604, 33605, 33606, 33607, 33609, 33610, 33611, 33612, 33613, 33614, 33616, 33617, 33618, 33619, 33620, 33621, 33629, 33634]

        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage=app_package,
            appActivity='com.poshmark.ui.MainActivity',
            language='en',
            locale='US',
            noReset=True,
            skipDeviceInitialization=True
        )

        super(PoshMarkClient, self).__init__(device_serial, logger, capabilities)

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
        except TimeoutException:
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
        download_location = f'/{download_folder}/{filename}'
        self.bucket.download_file(key, download_location)
        self.driver.push_file(destination_path=f'/sdcard/Pictures/{filename}', source_path=download_location)

    def alert_check(self):
        self.logger.info('Checking for an alert')
        if self.is_present(AppiumBy.ID, 'android:id/alertTitle'):
            title = self.locate(AppiumBy.ID, 'android:id/alertTitle').text

            if 'party' in title.lower():
                self.logger.info('Posh Party Alert found, clicking cancel button')
                cancel = self.locate(AppiumBy.ID, 'android:id/button2')
                self.click(cancel)

                return True
        elif self.is_present(AppiumBy.ID, 'android:id/message'):
            message = self.locate(AppiumBy.ID, 'android:id/message')

            self.logger.info(f'Alert with the following message popped up: {message.text}')

            ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
            self.click(ok_button)
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

    def register(self):
        campaign_folder = f'/{self.campaign.title}'
        campaign_folder_exists = os.path.exists(campaign_folder)
        if not campaign_folder_exists:
            os.mkdir(campaign_folder)

        profile_picture_key = self.campaign.posh_user.profile_picture.name
        self.download_and_send_file(profile_picture_key, campaign_folder)

        time.sleep(1)

        retries = 0
        while not self.is_present(AppiumBy.ID, 'sign_up_option') and retries < 30:
            self.sleep(7)
            retries += 1

        while self.is_present(AppiumBy.ID, 'sign_up_option'):
            self.logger.info('Clicked sign up button')
            sign_up = self.locate(AppiumBy.ID, 'sign_up_option')
            self.click(sign_up)
            self.sleep(1)

        if self.is_present(AppiumBy.ID, 'com.google.android.gms:id/cancel'):
            none_of_the_above = self.locate(AppiumBy.ID, 'com.google.android.gms:id/cancel')
            self.click(none_of_the_above)

        if self.is_present(AppiumBy.ID, 'avataarImageView'):
            picture_elem = self.locate(AppiumBy.ID, 'avataarImageView')
            self.click(picture_elem)

            photo_albums = self.locate(AppiumBy.ID, 'galleryTv')
            self.click(photo_albums)

            profile_picture = self.locate(AppiumBy.XPATH, f'//android.widget.LinearLayout[contains(@content-desc, "{profile_picture_key.split("/")[-1]}")]/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
            self.click(profile_picture)

            self.sleep(1)

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            first_name = self.locate(AppiumBy.ID, 'firstname')
            last_name = self.locate(AppiumBy.ID, 'lastname')
            email = self.locate(AppiumBy.ID, 'email')
            username = self.locate(AppiumBy.ID, 'username')
            password = self.locate(AppiumBy.ID, 'password')

            self.send_keys(first_name, self.campaign.posh_user.first_name)
            self.send_keys(last_name, self.campaign.posh_user.last_name)
            self.send_keys(email, self.campaign.posh_user.email)
            self.send_keys(username, self.campaign.posh_user.username)
            self.send_keys(password, self.campaign.posh_user.password)

            while not self.campaign.posh_user.is_registered:
                create_button = self.locate(AppiumBy.ID, 'nextButton')
                self.click(create_button)

                if self.is_present(AppiumBy.ID, 'popupContainer'):
                    new_username = self.locate(AppiumBy.ID, 'item')
                    self.click(new_username)

                    self.sleep(1)

                    username = self.locate(AppiumBy.ID, 'username')
                    self.campaign.posh_user.username = username.text
                    self.campaign.posh_user.save()

                while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('Registration still in progress')
                    self.sleep(3)

                response = requests.get(f'https://poshmark.com/closet/{self.campaign.posh_user.username}', timeout=30)
                if response.status_code != requests.codes.ok:
                    if self.is_present(AppiumBy.ID, 'android:id/message'):
                        ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
                        self.click(ok_button)

                    elif self.is_present(AppiumBy.ID, 'android:id/autofill_save_no'):
                        not_now = self.locate(AppiumBy.ID, 'android:id/autofill_save_no')
                        self.click(not_now)

                else:
                    self.campaign.posh_user.is_registered = True
                    self.campaign.posh_user.save()

            return self.finish_registration()
        else:
            return self.register_alt()
    
    def register_alt(self):
        try:
            first_name = self.locate(AppiumBy.ID, 'firstname')
            last_name = self.locate(AppiumBy.ID, 'lastname')
            email = self.locate(AppiumBy.ID, 'email')

            self.send_keys(first_name, self.campaign.posh_user.first_name)
            self.send_keys(last_name, self.campaign.posh_user.last_name)
            email.send_keys(self.campaign.posh_user.email)

            continue_button = self.locate(AppiumBy.ID, 'continueButton')
            continue_button.click()

            self.sleep(.5)

            while self.is_present(AppiumBy.ID, 'progressBar'):
                self.logger.info('Waiting to continue...')
                self.sleep(5)

            picture_elem = self.locate(AppiumBy.ID, 'addPictureButton')
            self.click(picture_elem)

            photo_albums = self.locate(AppiumBy.ID, 'galleryTv')
            self.click(photo_albums)

            profile_picture_key = self.campaign.posh_user.profile_picture.name
            profile_picture = self.locate(AppiumBy.XPATH,
                                          f'//android.widget.LinearLayout[contains(@content-desc, "{profile_picture_key.split("/")[-1]}")]/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
            self.click(profile_picture)

            self.sleep(1)

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            username = self.locate(AppiumBy.ID, 'username')
            password = self.locate(AppiumBy.ID, 'password')

            username.clear()
            username.send_keys(self.campaign.posh_user.username)
            password.send_keys(self.campaign.posh_user.password)

            while not self.campaign.posh_user.is_registered:
                create_button = self.locate(AppiumBy.ID, 'continueButton')
                self.click(create_button)

                if self.is_present(AppiumBy.ID, 'popupContainer'):
                    new_username = self.locate(AppiumBy.ID, 'item')
                    self.click(new_username)

                    self.sleep(1)

                    username = self.locate(AppiumBy.ID, 'username')
                    self.campaign.posh_user.username = username.text
                    self.campaign.posh_user.save()

                while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('Registration still in progress')
                    self.sleep(3)

                response = requests.get(f'https://poshmark.com/closet/{self.campaign.posh_user.username}', timeout=30)
                if response.status_code != requests.codes.ok:
                    if self.is_present(AppiumBy.ID, 'android:id/message'):
                        ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
                        self.click(ok_button)

                else:
                    self.campaign.posh_user.is_registered = True
                    self.campaign.posh_user.save()

                    if self.is_present(AppiumBy.ID, 'android:id/autofill_save_no'):
                        not_now = self.locate(AppiumBy.ID, 'android:id/autofill_save_no')
                        self.click(not_now)

            return self.finish_registration()
        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False

    def finish_registration(self):
        try:
            self.logger.info('Finishing registration')

            while not (self.is_present(AppiumBy.ID, 'continueButton') or self.is_present(AppiumBy.ID, 'nextButton')):
                self.logger.info('Waiting to continue')
                self.sleep(2)

                self.alert_check()

            if self.is_present(AppiumBy.ID, 'continueButton'):
                dress_size_id = 'clothingSize'
                shoe_size_id = 'shoeSize'
                zipcode_id = 'zip_code'
                continue_button_id = 'continueButton'
                done_button_id = 'nextButton'
                brand_logos_id = 'brandLogo'
            else:
                dress_size_id = 'sizeSpinnerText_II_InputLayout'
                shoe_size_id = 'sizeSpinnerText_I'
                zipcode_id = 'zip'
                continue_button_id = 'nextButton'
                done_button_id = 'nextButton'
                brand_logos_id = 'suggestedBrandLogo3'

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
            zip_input.send_keys(str(random.choice(self.zipcodes)))

            while not self.is_present(AppiumBy.ID, brand_logos_id):
                continue_button = self.locate(AppiumBy.ID, continue_button_id)
                self.click(continue_button)

                while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('Waiting for things to save')
                    self.sleep(3)

            self.logger.info('Selecting brands')

            brands = self.locate_all(AppiumBy.ID, brand_logos_id)[:12]
            for brand in random.choices(brands, k=random.randint(2, 6)):
                self.click(brand)

            while not self.is_present(AppiumBy.ID, 'sellTab'):
                if self.is_present(AppiumBy.ID, continue_button_id):
                    continue_button = self.locate(AppiumBy.ID, continue_button_id)
                    self.click(continue_button)
                elif self.is_present(AppiumBy.ID, done_button_id):
                    done_button = self.locate(AppiumBy.ID, done_button_id)
                    done_button.click()

                while self.is_present(AppiumBy.ID, 'progressBar') and not self.is_present(AppiumBy.ID, 'titleTextView'):
                    self.logger.info('Waiting for things to save')
                    self.sleep(3)

                self.alert_check()

            self.logger.info('Registration complete')

            return True
        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False

    def list_item(self, listing: Listing, listing_images: List[ListingImage]):
        try:
            self.logger.info(f'Listing {listing.title} for {self.campaign.posh_user.username}')

            campaign_folder = f'/{self.campaign.title}'
            listing_folder = f'/{self.campaign.title}/{listing.title}'
            campaign_folder_exists = os.path.exists(campaign_folder)
            listing_folder_exists = os.path.exists(listing_folder)

            if not campaign_folder_exists:
                os.mkdir(f'/{self.campaign.title}')

            if not listing_folder_exists:
                os.mkdir(f'/{self.campaign.title}/{listing.title}')

            cover_photo_key = listing.cover_photo.name
            self.download_and_send_file(cover_photo_key, listing_folder)

            listing_images.reverse()
            for listing_image in listing_images:
                image_key = listing_image.image.name
                self.download_and_send_file(image_key, listing_folder)

            sell_button = self.locate(AppiumBy.ID, 'sellTab')
            self.click(sell_button)

            self.logger.info('Sell button clicked')

            if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
                deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
                self.click(deny_button)
                self.logger.info('Denying access to camera')

            gallery_button = self.locate(AppiumBy.ID, 'gallery')
            self.click(gallery_button)

            if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button'):
                allow_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button')
                self.click(allow_button)

            self.sleep(4)
            self.tap_img(cover_photo_key.split("/")[-1])

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            self.sleep(1)

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            self.sleep(1)

            add_more_button = self.locate(AppiumBy.ID, 'add_more')
            self.click(add_more_button)

            if self.is_present(AppiumBy.ID,
                               'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button'):
                deny_button = self.locate(AppiumBy.ID,
                                          'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button')
                self.click(deny_button)

                self.sleep(1)
            if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
                deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
                self.click(deny_button)

            gallery_button = self.locate(AppiumBy.ID, 'gallery')
            self.click(gallery_button)

            self.sleep(1)

            group_num = 0
            self.swipe('up', 530)
            self.sleep(.75)
            for x in range(1, len(listing_images) + 1):
                img_index = x - group_num
                img = self.locate(AppiumBy.XPATH,
                                  f'/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.view.ViewGroup/androidx.drawerlayout.widget.DrawerLayout/android.widget.ScrollView/android.widget.FrameLayout/android.widget.FrameLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/androidx.recyclerview.widget.RecyclerView/androidx.cardview.widget.CardView[{img_index}]/androidx.cardview.widget.CardView/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
                if x == 1:
                    self.long_click(img)
                else:
                    img.click()

                if x % 6 == 0 and x != len(listing_images):
                    self.swipe('up', 580 * 3)
                    group_num += 4 if not group_num else 6
                    self.sleep(.75)

            select_button = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/action_menu_select')
            self.click(select_button)

            self.sleep(2)

            if self.is_present(AppiumBy.ID, 'nextButton'):
                next_button = self.locate(AppiumBy.ID, 'nextButton')
                self.click(next_button)
            else:
                self.click(element=None, x=500, y=500)

                next_button = self.locate(AppiumBy.ID, 'nextButton')
                self.click(next_button)

            self.sleep(2)

            title_input = self.locate(AppiumBy.ID, 'title_edit_text')
            title_input.send_keys(listing.title)

            description_body = self.locate(AppiumBy.ID, 'description_body')
            self.click(description_body)

            description_input = self.locate(AppiumBy.ID, 'description_editor')
            self.send_keys(description_input, str(listing.description))

            done_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(done_button)

            self.sleep(1)

            media_items = self.locate(AppiumBy.ID, 'media_items')
            description_body = self.locate(AppiumBy.ID, 'description_body')
            self.swipe('up', 600 + media_items.size['height'] + description_body.size['height'])

            listing_category = listing.category
            space_index = listing_category.find(' ')
            primary_category = listing_category[:space_index]
            secondary_category = listing_category[space_index + 1:]

            category = self.locate(AppiumBy.ID, 'catalog_edit_text')
            self.click(category)

            self.sleep(1)

            primary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, primary_category.lower())
            self.click(primary_category_button)

            self.sleep(1)

            secondary_category_clicked = False
            secondary_category_click_attempts = 0
            while not secondary_category_clicked and secondary_category_click_attempts < 3:
                try:
                    secondary_category_click_attempts += 1
                    secondary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, secondary_category.lower())
                    self.click(secondary_category_button)
                    self.sleep(.5)
                    secondary_category_clicked = True
                except TimeoutException:
                    self.swipe('up', 400)
                    self.sleep(.5)

            subcategory_clicked = False
            subcategory_click_attempts = 0
            while not subcategory_clicked and subcategory_click_attempts < 3:
                try:
                    subcategory_click_attempts += 1
                    subcategory_button = self.locate(AppiumBy.ACCESSIBILITY_ID, listing.subcategory.lower())
                    self.click(subcategory_button)
                    self.logger.info('Clicked sub category')
                    self.sleep(1)
                    subcategory_clicked = True
                except TimeoutException:
                    self.swipe('up', 400)
                    self.sleep(.5)

            done_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(done_button)

            self.logger.info('Clicked done button')

            pressed_back = False
            if self.locate(AppiumBy.ID, 'titleTextView').text == 'Select Category':
                for _ in range(3):
                    self.driver.back()
                    self.sleep(.5)
                pressed_back = True

            self.sleep(.5)

            if pressed_back:
                media_items = self.locate(AppiumBy.ID, 'media_items')
                description_body = self.locate(AppiumBy.ID, 'description_body')
                self.swipe('up', 600 + media_items.size['height'] + description_body.size['height'])

            self.logger.info('Putting in size')

            size_button = self.locate(AppiumBy.ID, 'size_edit_text')
            self.click(size_button)

            if 'belt' in (listing_category + ' ' + listing.subcategory).lower():
                custom_size_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Custom')
                self.click(custom_size_button)

                add_option = self.locate(AppiumBy.ID, 'container')
                self.click(add_option)

                custom_size_input = self.locate(AppiumBy.ID, 'messageText')
                custom_size_input.send_keys(listing.size)

                next_button = self.locate(AppiumBy.ID, 'nextButton')
                self.click(next_button)
            else:
                one_size = self.locate(AppiumBy.ACCESSIBILITY_ID, 'One Size')
                self.click(one_size)

            self.sleep(.5)

            pressed_back = False
            if self.locate(AppiumBy.ID, 'titleTextView').text == 'Select Category':
                self.logger.info('Category issue popped up... Pressing back button.')
                for _ in range(3):
                    self.driver.back()
                    self.sleep(.5)
                pressed_back = True

            self.sleep(.5)

            if pressed_back:
                media_items = self.locate(AppiumBy.ID, 'media_items')
                description_body = self.locate(AppiumBy.ID, 'description_body')
                self.swipe('up', 600 + media_items.size['height'] + description_body.size['height'])

            self.sleep(1)
            self.logger.info('Putting in brand')

            brand_input = self.locate(AppiumBy.ID, 'brand_edit_text')
            while brand_input.text != listing.brand:
                pressed_back = False
                self.click(brand_input)
                self.logger.info('Clicked brand button')

                brand_search = self.locate(AppiumBy.ID, 'searchTextView')
                brand_search.send_keys(listing.brand)

                if not self.is_present(AppiumBy.ACCESSIBILITY_ID, listing.brand):
                    self.logger.info('Brand did not pop up on search... Taping back.')
                    while not self.is_present(AppiumBy.ID, 'titleTextView') or self.locate(AppiumBy.ID,
                                                                                           'titleTextView').text != 'Listing Details':
                        self.driver.back()
                        self.sleep(.5)
                    pressed_back = True

                else:
                    brand = self.locate(AppiumBy.ACCESSIBILITY_ID, listing.brand)
                    self.click(brand)

                    self.logger.info('Clicked brand')

                    if self.locate(AppiumBy.ID, 'titleTextView').text == 'Select Category':
                        for _ in range(3):
                            self.driver.back()
                            self.sleep(.5)
                        pressed_back = True

                if pressed_back:
                    self.logger.info('Scrolling...')
                    media_items = self.locate(AppiumBy.ID, 'media_items')
                    description_body = self.locate(AppiumBy.ID, 'description_body')
                    self.swipe('up', 600 + media_items.size['height'] + description_body.size['height'])

                    self.sleep(1)

                brand_input = self.locate(AppiumBy.ID, 'brand_edit_text')

            while not self.is_present(AppiumBy.ID, 'listing_price_edit_text'):
                self.swipe('up', 600)
                self.sleep(1)

            original_price = self.locate(AppiumBy.ID, 'original_price_edit_text')
            listing_price = self.locate(AppiumBy.ID, 'listing_price_edit_text')

            original_price.send_keys(str(listing.original_price))
            listing_price.send_keys(str(listing.listing_price))

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            self.sleep(1)

            next_button = self.locate(AppiumBy.ID, 'nextButton')
            self.click(next_button)

            list_attempts = 0
            self.logger.info('Sell button clicked')
            self.sleep(5)
            sell_button_present = self.is_present(AppiumBy.ID, 'sellTab')

            while not sell_button_present and list_attempts < 20:
                sell_button_present = self.is_present(AppiumBy.ID, 'sellTab')
                list_attempts += 1

                if self.is_present(AppiumBy.ID, 'android:id/alertTitle'):
                    error_title = self.locate(AppiumBy.ID, 'android:id/alertTitle')
                    if 'error' in error_title.text.lower():
                        self.logger.info('Error occurred, clicking retry button')
                        retry_button = self.locate(AppiumBy.ID, 'android:id/button1')
                        self.click(retry_button)
                    else:
                        self.logger.info('Some alert popped up but it is not implemented')
                        self.sleep(5)
                elif self.is_present(AppiumBy.XPATH, f"//*[contains(@text, 'Certify Listing')]"):
                    self.logger.warning('Certify listing page came up. Clicking certify.')
                    certify_button = self.locate(AppiumBy.XPATH, f"//*[contains(@text, 'Certify Listing')]")
                    self.click(certify_button)

                    self.sleep(.5)
                    certify_ok = self.locate(AppiumBy.ID, 'android:id/button1')
                    self.click(certify_ok)

                else:
                    self.logger.info('Item not listed yet')
                    self.sleep(10)
            else:
                if list_attempts >= 10:
                    self.logger.error(f'Attempted to locate the sell button {list_attempts} times but could not find it.')
                    return False
                else:
                    self.logger.info('Item listed successfully')

            return True
        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False


class AppClonerClient(AppiumClient):
    def __init__(self, device_serial, logger, app_name=None):
        self.driver = None
        self.logger = logger
        self.app_name = app_name

        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            appPackage='com.applisto.appcloner',
            appActivity='.activity.MainActivity',
            language='en',
            locale='US',
            noReset=True,
            skipDeviceInitialization=True
        )
        super(AppClonerClient, self).__init__(device_serial, logger, capabilities)

    def add_clone(self):
        try:
            poshmark_app = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.drawerlayout.widget.DrawerLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/android.widget.LinearLayout/androidx.viewpager.widget.ViewPager/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.ListView/android.widget.FrameLayout[2]/android.widget.LinearLayout/android.widget.TextView')
            poshmark_app.click()

            self.sleep(.5)

            clone_number = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.drawerlayout.widget.DrawerLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/android.widget.LinearLayout/androidx.viewpager.widget.ViewPager/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.view.ViewGroup/android.widget.ListView/android.widget.LinearLayout[1]/android.widget.RelativeLayout')
            clone_number.click()

            clone_number_input = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.ScrollView/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.EditText')
            clone_number_input.clear()
            clone_number_input.send_keys('1')

            while self.is_present(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.ScrollView/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.TextView'):
                next_button = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.ScrollView/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.LinearLayout[1]/android.widget.ImageView[2]')
                next_button.click()

            ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
            ok_button.click()

            clone_name = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.drawerlayout.widget.DrawerLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/android.widget.LinearLayout/androidx.viewpager.widget.ViewPager/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.view.ViewGroup/android.widget.ListView/android.widget.LinearLayout[2]/android.widget.RelativeLayout')
            clone_name.click()

            clone_name_input = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.ScrollView/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout[1]/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.EditText')
            clone_name_input.clear()
            clone_name_input.send_keys(self.app_name)

            ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
            ok_button.click()

            clone_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Clone app')
            clone_button.click()

            while self.is_present(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.TextView'):
                title = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.appcompat.widget.LinearLayoutCompat/android.widget.LinearLayout/android.widget.LinearLayout/android.widget.TextView')
                if title.text == 'Cloning Poshmark':
                    self.logger.info('Waiting for app to finish cloning...')
                    self.sleep(8)
                elif title.text == 'App cloned':
                    self.logger.info('App finished cloning')
                    install_button = self.locate(AppiumBy.ID, 'android:id/button1')
                    install_button.click()

            self.sleep(.5)

            install_button = self.locate(AppiumBy.ID, 'android:id/button1')
            install_button.click()

            while self.is_present(AppiumBy.ID, 'com.android.packageinstaller:id/progress'):
                self.logger.info('Waiting for app to finish installing...')
                self.sleep(3)

            self.logger.info('Installation completed')

            if self.is_present(AppiumBy.ID, 'android:id/button2'):
                done_button = self.locate(AppiumBy.ID, 'android:id/button2')
                done_button.click()
        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False

    def launch_clone(self):
        try:
            self.logger.info('Launching app')
            clones_button = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.drawerlayout.widget.DrawerLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.FrameLayout/android.view.View[2]')
            clones_button.click()

            while not self.is_present(AppiumBy.XPATH, f"//*[contains(@text, '{self.app_name}')]"):
                self.swipe('up', 1300)

            clone = self.locate(AppiumBy.XPATH, f"//*[contains(@text, '{self.app_name}')]")
            clone.click()

            self.sleep(.5)

            launch_button = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[2]')
            launch_button.click()
        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)

            return False

    def delete_clone(self, app_names):
        try:
            self.logger.info('Launching app')
            clones_button = self.locate(AppiumBy.XPATH,
                                        '/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/androidx.drawerlayout.widget.DrawerLayout/android.widget.LinearLayout/android.widget.LinearLayout[2]/android.widget.LinearLayout/android.widget.FrameLayout/android.view.View[2]')
            clones_button.click()

            for app_name in sorted(app_names):
                try:
                    clone = self.locate(AppiumBy.XPATH, f"//*[contains(@text, '{app_name}')]")
                    clone.click()

                    self.sleep(.5)

                    uninstall_button = self.locate(AppiumBy.XPATH,
                                                   '/hierarchy/android.widget.FrameLayout/androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout[3]')
                    uninstall_button.click()

                    ok_button = self.locate(AppiumBy.ID, 'android:id/button1')
                    ok_button.click()
                except TimeoutException:
                    scroll_attempts = 0
                    while not self.is_present(AppiumBy.XPATH, f"//*[contains(@text, '{app_name}')]") and scroll_attempts < 40:
                        self.swipe('up', 1300)
                        scroll_attempts += 1

        except TimeoutException:
            self.logger.error(traceback.format_exc())
            self.logger.info(self.driver.page_source)
