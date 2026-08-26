from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver


DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS = 30


def create_local_chrome_driver(run_in_headless_mode: bool = True) -> WebDriver:
    """建立本機開發環境使用的 Chrome Driver。"""
    chrome_options = Options()

    # 指定瀏覽器視窗大小，避免 Headless 模式下使用手機版頁面。
    chrome_options.add_argument("--window-size=1920,1080")

    if run_in_headless_mode:
        # Headless 模式不會顯示 Chrome 視窗。
        chrome_options.add_argument("--headless=new")

    # 不指定 ChromeDriver 路徑，交由 Selenium Manager 處理。
    chrome_driver = webdriver.Chrome(options=chrome_options)

    # 避免網頁長時間沒有載入完成，導致程式永遠卡住。
    chrome_driver.set_page_load_timeout(
        DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS
    )

    return chrome_driver