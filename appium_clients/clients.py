import boto3
import os
import random
import requests
import time

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from django.conf import settings
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException
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
                cancel.click()

                return True
        else:
            self.logger.info('No posh party alert')
        return False

    def tap_img(self, name):
        search_box = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/searchbar_title')
        search_box.click()

        search_input = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/search_src_text')
        search_input.send_keys(name)

        self.sleep(1)

        img = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/icon_thumb')
        img.click()

    def register(self):
        campaign_folder = f'/{self.campaign.title}'
        campaign_folder_exists = os.path.exists(campaign_folder)
        if not campaign_folder_exists:
            os.mkdir(campaign_folder)

        profile_picture_key = self.campaign.posh_user.profile_picture.name
        self.download_and_send_file(profile_picture_key, campaign_folder)

        retries = 0
        while not self.is_present(AppiumBy.ID, 'com.poshmark.app:id/sign_up_option') and retries < 10:
            self.sleep(7)
            retries += 1

        sign_up = self.locate(AppiumBy.ID, 'com.poshmark.app:id/sign_up_option')
        sign_up.click()

        if self.is_present(AppiumBy.ID, 'com.google.android.gms:id/cancel'):
            none_of_the_above = self.locate(AppiumBy.ID, 'com.google.android.gms:id/cancel')
            none_of_the_above.click()

        picture_elem = self.locate(AppiumBy.ID, 'com.poshmark.app:id/avataarImageView')
        picture_elem.click()

        photo_albums = self.locate(AppiumBy.ID, 'com.poshmark.app:id/galleryTv')
        photo_albums.click()

        profile_picture = self.locate(AppiumBy.XPATH, f'//android.widget.LinearLayout[contains(@content-desc, "{profile_picture_key.split("/")[-1]}")]/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
        profile_picture.click()

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        first_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/firstname')
        last_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/lastname')
        email = self.locate(AppiumBy.ID, 'com.poshmark.app:id/email')
        username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/username')
        password = self.locate(AppiumBy.ID, 'com.poshmark.app:id/password')

        first_name.send_keys(self.campaign.posh_user.first_name)
        last_name.send_keys(self.campaign.posh_user.last_name)
        email.send_keys(self.campaign.posh_user.email)
        username.send_keys(self.campaign.posh_user.username)
        password.send_keys(self.campaign.posh_user.password)

        while not self.campaign.posh_user.is_registered:
            create_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
            create_button.click()

            if self.is_present(AppiumBy.ID, 'com.poshmark.app:id/popupContainer'):
                new_username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/item')
                new_username.click()

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
                    ok_button.click()

                elif self.is_present(AppiumBy.ID, 'android:id/autofill_save_no'):
                    not_now = self.locate(AppiumBy.ID, 'android:id/autofill_save_no')
                    not_now.click()

            else:
                self.campaign.posh_user.is_registered = True
                self.campaign.posh_user.save()

        next_button_clicks = 0

        while next_button_clicks < 3:
            try:
                next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
                next_button.click()
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
        sell_button.click()

        if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
            deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
            deny_button.click()

        gallery_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/gallery')
        gallery_button.click()

        if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button'):
            allow_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_allow_button')
            allow_button.click()

        self.sleep(4)
        self.tap_img(cover_photo_key.split("/")[-1])

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        self.sleep(1)

        add_more_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/add_more')
        add_more_button.click()

        for x in range(len(listing_images)):
            if x == 0:
                if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button'):
                    deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button')
                    deny_button.click()

                    self.sleep(1)
                if self.is_present(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button'):
                    deny_button = self.locate(AppiumBy.ID, 'com.android.permissioncontroller:id/permission_deny_button')
                    deny_button.click()

                gallery_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/gallery')
                gallery_button.click()

            img = self.locate(AppiumBy.XPATH, f'/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.view.ViewGroup/androidx.drawerlayout.widget.DrawerLayout/android.widget.ScrollView/android.widget.FrameLayout/android.widget.FrameLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/androidx.recyclerview.widget.RecyclerView/androidx.cardview.widget.CardView[{x + 1}]/androidx.cardview.widget.CardView/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')

            if x == 0:
                actions = ActionChains(self.driver).click_and_hold(img).pause(1).release(img)
                actions.perform()
            else:
                img.click()

            if x % 2 == 1 and (x + 1) != len(listing_images):
                img = self.locate(AppiumBy.XPATH, f'/hierarchy/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.view.ViewGroup/androidx.drawerlayout.widget.DrawerLayout/android.widget.ScrollView/android.widget.FrameLayout/android.widget.FrameLayout[2]/android.widget.LinearLayout/android.view.ViewGroup/androidx.recyclerview.widget.RecyclerView/androidx.cardview.widget.CardView[{x + 1}]/androidx.cardview.widget.CardView/android.widget.RelativeLayout/android.widget.FrameLayout[1]/android.widget.ImageView[1]')
                action = ActionChains(self.driver).click_and_hold(on_element=img).move_by_offset(xoffset=0, yoffset=-600)
                action.perform()

        select_button = self.locate(AppiumBy.ID, 'com.google.android.documentsui:id/action_menu_select')
        select_button.click()

        self.sleep(2)

        TouchAction(self.driver).tap(x=100, y=100).perform()

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        self.sleep(2)

        title_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/title_edit_text')
        title_input.send_keys(listing.title)

        description_body = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_body')
        description_body.click()

        description_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_editor')
        for text in listing.description.split('\n'):
            description_input.send_keys(text)
            ActionChains(self.driver).key_down(Keys.SHIFT).key_down(Keys.ENTER).key_up(Keys.SHIFT).key_up(Keys.ENTER).perform()

        done_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        done_button.click()

        self.sleep(1)

        description_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/description_body')
        action = ActionChains(self.driver).click_and_hold(on_element=description_input).move_by_offset(xoffset=0, yoffset=(-1658 - description_input.size['height']))
        action.perform()

        listing_category = listing.category
        space_index = listing_category.find(' ')
        primary_category = listing_category[:space_index]
        secondary_category = listing_category[space_index + 1:]

        category = self.locate(AppiumBy.ID, 'com.poshmark.app:id/catalog_edit_text')
        category.click()

        primary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, primary_category.lower())
        primary_category_button.click()

        self.sleep(1)

        primary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, primary_category.lower())
        action = ActionChains(self.driver).click_and_hold(on_element=primary_category_button).move_by_offset(xoffset=0, yoffset=-400)
        action.perform()

        secondary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, secondary_category.lower())
        secondary_category_button.click()

        self.sleep(1)

        secondary_category_button = self.locate(AppiumBy.ACCESSIBILITY_ID, secondary_category.lower())
        action = ActionChains(self.driver).click_and_hold(on_element=secondary_category_button).move_by_offset(xoffset=0, yoffset=-400)
        action.perform()

        subcategory_button = self.locate(AppiumBy.ACCESSIBILITY_ID, listing.subcategory.lower())
        subcategory_button.click()

        self.sleep(1)

        done_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        done_button.click()

        size_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/size_edit_text')
        size_button.click()

        custom_size_button = self.locate(AppiumBy.ACCESSIBILITY_ID, 'Custom')
        custom_size_button.click()

        add_option = self.locate(AppiumBy.ID, 'com.poshmark.app:id/container')
        add_option.click()

        custom_size_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/messageText')
        custom_size_input.send_keys(listing.size)

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        self.sleep(1)

        brand_input = self.locate(AppiumBy.ID, 'com.poshmark.app:id/brand_edit_text')
        brand_input.send_keys(listing.brand)

        original_price = self.locate(AppiumBy.ID, 'com.poshmark.app:id/original_price_edit_text')
        listing_price = self.locate(AppiumBy.ID, 'com.poshmark.app:id/listing_price_edit_text')

        original_price.send_keys(str(listing.original_price))
        listing_price.send_keys(str(listing.listing_price))

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

        self.sleep(1)

        next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        next_button.click()

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
