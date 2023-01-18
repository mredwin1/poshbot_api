import os
import random
import time

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from core.models import Campaign

appium_server_url = os.environ.get('APPIUM_SERVER_URL')


class AppiumClient:
    def __init__(self, campaign: Campaign, logger, proxy_ip=None, proxy_port=None):
        self.driver = None
        self.campaign = campaign
        self.logger = logger

        self.capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            deviceName='Galaxy S10',
            udid='R38M20JTJZJ',
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
            self.locate(by, locator)
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

    def register(self):
        time.sleep(5)

        # self.driver.push_file(destination_path='/mnt/sdcard/DCIM/Camera/profile.png',
        #                       source_path='C:\\Users\\Edwin Cruz\\Desktop\\users\\profile.png')
        # self.driver.push_file(destination_path='/mnt/sdcard/DCIM/Camera/header.png',
        #                       source_path='C:\\Users\\Edwin Cruz\\Desktop\\users\\header.png')

        sign_up = self.locate(AppiumBy.ID, 'com.poshmark.app:id/sign_up_option')
        sign_up.click()

        if self.is_present(AppiumBy.ID, 'com.google.android.gms:id/cancel'):
            none_of_the_above = self.locate(AppiumBy.ID, 'com.google.android.gms:id/cancel')
            none_of_the_above.click()

        first_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/firstname')
        last_name = self.locate(AppiumBy.ID, 'com.poshmark.app:id/lastname')
        email = self.locate(AppiumBy.ID, 'com.poshmark.app:id/email')
        continue_btn = self.locate(AppiumBy.ID, 'com.poshmark.app:id/continueButton')

        first_name.send_keys(self.campaign.posh_user.first_name)
        last_name.send_keys(self.campaign.posh_user.last_name)
        email.send_keys(self.campaign.posh_user.email)
        continue_btn.click()

        continue_btn = self.locate(AppiumBy.ID, 'com.poshmark.app:id/continueButton')
        username = self.locate(AppiumBy.ID, 'com.poshmark.app:id/username')
        password = self.locate(AppiumBy.ID, 'com.poshmark.app:id/password')
        # profile_picture = self.locate(AppiumBy.ID, 'com.poshmark.app:id/addPictureButton')

        posh_username = username.text

        password.send_keys('Akatt12345')
        # profile_picture.click()
        #
        # photo_album = self.locate(AppiumBy.ID, 'com.poshmark.app:id/galleryTv')
        # photo_album.click()
        #
        # first_image = self.locate(AppiumBy.XPATH, '/hierarchy/android.widget.FrameLayout/android.widget.FrameLayout/android.widget.FrameLayout/android.view.ViewGroup/android.support.v4.widget.DrawerLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.widget.FrameLayout/android.widget.LinearLayout/android.view.ViewGroup/android.support.v7.widget.RecyclerView/android.widget.LinearLayout[1]/android.widget.RelativeLayout/android.widget.FrameLayout/android.widget.ImageView[1]')
        # first_image.click()
        #
        # next_button = self.locate(AppiumBy.ID, 'com.poshmark.app:id/nextButton')
        # next_button.click()

        # time.sleep(5)
        continue_btn.click()
        time.sleep(10)
        self.campaign.posh_user.username = posh_username
        self.campaign.posh_user.is_registered = True
        self.campaign.posh_user.save()

    def list_item(self):
        pass

