from unittest import TestCase
from unittest.mock import patch

from analyses.providers.selenium.driver_factory import create_local_chrome_driver


class SeleniumDriverFactoryTests(TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("analyses.providers.selenium.driver_factory.webdriver.Chrome")
    def test_uses_local_chrome_without_remote_url(self, mock_chrome):
        driver = create_local_chrome_driver()

        self.assertIs(driver, mock_chrome.return_value)
        mock_chrome.assert_called_once()
        driver.set_page_load_timeout.assert_called_once_with(30)

    @patch.dict("os.environ", {"SELENIUM_REMOTE_URL": "http://selenium:4444/wd/hub"}, clear=True)
    @patch("analyses.providers.selenium.driver_factory.webdriver.Remote")
    def test_uses_remote_chrome_when_remote_url_is_configured(self, mock_remote):
        driver = create_local_chrome_driver()

        self.assertIs(driver, mock_remote.return_value)
        self.assertEqual(mock_remote.call_args.kwargs["command_executor"], "http://selenium:4444/wd/hub")
        driver.set_page_load_timeout.assert_called_once_with(30)
