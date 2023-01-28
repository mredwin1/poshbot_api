import boto3
import os
import random
import requests
import time

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from django.conf import settings
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException, InvalidArgumentException
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from typing import List

from core.models import Campaign, Listing, ListingImage

appium_server_url = os.environ.get('APPIUM_SERVER_URL')


class AppiumClient:
    def __init__(self, campaign: Campaign, logger, proxy_ip=None, proxy_port=None):
        self.driver = None
        self.campaign = campaign
        self.logger = logger
        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)
        self.bucket = s3_client.Bucket(settings.AWS_STORAGE_BUCKET_NAME)

        self.capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            deviceName='Pixel 3',
            udid='94TXS0P38',
            appPackage='com.poshmark.app',
            appActivity='com.poshmark.ui.MainActivity',
            language='en',
            locale='US',

        )

    def __enter__(self):
        self.open()

        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def open(self):
        """Used to open the appium web driver session"""
        self.driver = webdriver.Remote(appium_server_url, self.capabilities)

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

    def swipe(self, direction, scroll_amount):
        window_size = self.driver.get_window_size()
        if direction in ('up', 'down'):
            bounding_box_xpercent_min = .5
            bounding_box_xpercent_max = .9
            bounding_box_ypercent_min = .1
            bounding_box_ypercent_max = .8
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
                'speed': 1200
            })
            if index + 1 != len(scroll_percents):
                self.sleep(.5)

    def send_keys(self, element, text):
        word = None
        char = None
        self.click(element)
        for index, line in enumerate(text.split('\n')):
            action = ActionChains(self.driver)

            if index != 0:
                self.driver.press_keycode(66)

            words = line.split(' ')

            for inner_index, word in enumerate(words):
                try:
                    for char in word:
                        action.send_keys(char).pause(random.uniform(.1, .2))

                    if len(words) > 1 and inner_index != len(words) - 1:
                        action.send_keys(' ')

                    action.perform()
                except InvalidArgumentException:
                    self.logger.info(word)
                    self.logger.info(char)

        self.driver.back()

    def download_and_send_file(self, key, download_folder):
        filename = key.split('/')[-1]
        download_location = f'/{download_folder}/{filename}'
        self.bucket.download_file(key, download_location)
        self.driver.push_file(destination_path=f'/sdcard/Pictures/{filename}', source_path=download_location)

    def alert_check(self):
        self.logger.info('Checking for posh party alert')
        if self.is_present(AppiumBy.ID, 'android:id/alertTitle'):
            title = self.locate(AppiumBy.ID, 'android:id/alertTitle').text

            if 'party' in title.lower():
                self.logger.info('Alert found, clicking cancel button')
                cancel = self.locate(AppiumBy.ID, 'android:id/button2')
                self.click(cancel)

                return True
        else:
            self.logger.info('No posh party alert')
        return False

    def tap_img(self, name):
        search_box = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/searchbar_title')
        self.click(search_box)

        search_input = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/search_src_text')
        search_input.send_keys(name)

        self.sleep(1)

        self.driver.back()

        img = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/icon_thumb')
        self.click(img)

    def register(self):
        campaign_folder = f'/{self.campaign.title}'
        campaign_folder_exists = os.path.exists(campaign_folder)
        if not campaign_folder_exists:
            os.mkdir(campaign_folder)

        profile_picture_key = self.campaign.posh_user.profile_picture.name
        self.download_and_send_file(profile_picture_key, campaign_folder)

        time.sleep(1)

        retries = 0
        while not self.is_present(AppiumBy.ID, 'com.poshmark.app:id/sign_up_option') and retries < 10:
            self.sleep(7)
            retries += 1

        sign_up = self.locate(AppiumBy.ID, 'com.poshmark.app:id/sign_up_option')
        self.click(sign_up)

        if self.is_present(AppiumBy.ID, 'com.google.android.gms:id/cancel'):
            none_of_the_above = self.locate(AppiumBy.ID, 'com.google.android.gms:id/cancel')
            self.click(none_of_the_above)

        picture_elem = self.locate(AppiumBy.ID, 'com.poshmark.app:id/avataarImageView')
        self.click(picture_elem)

        photo_albums = self.locate(AppiumBy.ID, 'com.poshmark.app:id/galleryTv')
        self.click(photo_albums)

        profile_picture = self.locate(AppiumBy.XPATH, f'//android.widget.LinearLayout[contains(@content-desc, "{profile_picture_key.split("/")[-1]}")]/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
        self.click(profile_picture)

        self.sleep(1)

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(next_button)

        first_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/firstname')
        last_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/lastname')
        email = self.locate(AppiumBy.ID, 'com.poshmark.app:id/email')
        username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/username')
        password = self.locate(AppiumBy.ID, 'com.poshmark.app:id/password')

        self.send_keys(first_name, self.campaign.posh_user.first_name)
        self.send_keys(last_name, self.campaign.posh_user.last_name)
        self.send_keys(email, self.campaign.posh_user.email)
        self.send_keys(username, self.campaign.posh_user.username)
        self.send_keys(password, self.campaign.posh_user.password)

        while not self.campaign.posh_user.is_registered:
            create_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
            self.click(create_button)

            if self.is_present(AppiumBy.ID, 'com.poshmark.app:id/popupContainer'):
                new_username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/item')
                self.click(new_username)

                self.sleep(1)

                username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/username')
                self.campaign.posh_user.username = username.text
                self.campaign.posh_user.save()

            progress_bar_checks = 0
            while self.is_present(AppiumBy.ID, 'com.poshmark.app:id/progressBar') and progress_bar_checks < 40:
                self.logger.info('Registration still in progress')
                progress_bar_checks += 1
                self.sleep(5)

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

        next_button_clicks = 0

        while next_button_clicks < 3:
            try:
                next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
                self.click(next_button)
                next_button_clicks += 1
                self.logger.info('Next button clicked')
            except TimeoutException:
                self.logger.warning('Next button could not be found')
                self.sleep(2)

    def list_item(self, listing: Listing, listing_images: List[ListingImage]):
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

        self.alert_check()

        sell_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/sellTab')
        self.click(sell_button)

        if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
            deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
            self.click(deny_button)

        gallery_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/gallery')
        self.click(gallery_button)

        if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button'):
            allow_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button')
            self.click(allow_button)

        self.sleep(4)
        self.tap_img(cover_photo_key.split("/")[-1])

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(next_button)

        self.sleep(1)

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(next_button)

        self.sleep(1)

        add_more_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/add_more')
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

        gallery_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/gallery')
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
                self.click(img)

            if x % 6 == 0 and x != len(listing_images):
                self.swipe('up', 580 * 3)
                group_num += 4 if not group_num else 6
                self.sleep(.75)

        select_button = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/action_menu_select')
        self.click(select_button)

        self.sleep(2)

        if self.is_present(AppiumBy.ID, 'com.poshmark.app:id/nextButton'):
            next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
            self.click(next_button)
        else:
            self.click(element=None, x=500, y=500)

            next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
            self.click(next_button)

        self.sleep(2)

        title_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/title_edit_text')
        title_input.send_keys(listing.title)

        description_body = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_body')
        self.click(description_body)

        description_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_editor')
        self.send_keys(description_input, str(listing.description))

        done_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(done_button)

        self.sleep(1)

        media_items = self.locate(AppiumBy.ID, 'com.poshmark.app:id/media_items')
        description_body = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_body')
        self.swipe('up', 600 + media_items.size['height'] + description_body.size['height'])

        listing_category = listing.category
        space_index = listing_category.find(' ')
        primary_category = listing_category[:space_index]
        secondary_category = listing_category[space_index + 1:]

        category = self.locate(AppiumBy.ID, 'com.poshmark.app:id/catalog_edit_text')
        self.click(category)

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
                subcategory_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Wallets'.lower())
                self.click(subcategory_button)
                self.sleep(.5)
                subcategory_clicked = True
            except TimeoutException:
                self.swipe('up', 400)
                self.sleep(.5)

        done_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(done_button)

        size_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/size_edit_text')
        self.click(size_button)

        if 'belt' in (listing_category + ' ' + listing.subcategory).lower():
            custom_size_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Custom')
            self.click(custom_size_button)

            add_option = self.locate(AppiumBy.ID, 'com.poshmark.app:id/container')
            self.click(add_option)

            custom_size_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/messageText')
            custom_size_input.send_keys(listing.size)

            next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
            self.click(next_button)
        else:
            one_size = self.locate(AppiumBy.ACCESSIBILITY_ID, 'One Size')
            self.click(one_size)

        self.sleep(1)

        brand_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/brand_edit_text')
        brand_input.send_keys(listing.brand)

        original_price = self.locate(AppiumBy.ID, 'com.poshmark.app:id/original_price_edit_text')
        listing_price = self.locate(AppiumBy.ID, 'com.poshmark.app:id/listing_price_edit_text')

        original_price.send_keys(str(listing.original_price))
        listing_price.send_keys(str(listing.listing_price))

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(next_button)

        self.sleep(1)

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        self.click(next_button)

        list_attempts = 0
        self.logger.info('Sell button clicked')
        self.sleep(5)
        sell_button_present = self.is_present(AppiumBy.ID, 'com.poshmark.app:id/sellTab')

        while not sell_button_present and list_attempts < 10:
            sell_button_present = self.is_present(AppiumBy.ID, 'com.poshmark.app:id/sellTab')
            list_attempts += 1
            self.logger.info('Item not listed yet')
            self.sleep(10)
        else:
            if list_attempts >= 10:
                self.logger.error(f'Attempted to locate the sell button {list_attempts} times but could not find it.')
                return False
            else:
                self.logger.info('Item listed successfully')

        return True

    def reset_data(self):
        self.driver.reset()
