from django.test import TestCase #TestCase：每個測試之間隔離資料庫資料。
from django.urls import reverse #reverse()：透過 URL 名稱取得網址。


class OverviewViewTests(TestCase): #這是Django 內建的測試指令。它會自動尋找 analyses/tests.py 內符合規則的測試：
    """分析總覽頁面的基本測試。"""

    def test_overview_page_renders_expected_content(self):
        response = self.client.get(reverse("analyses:overview")) #模擬瀏覽器向 Django 發送請求。

        #確認首頁能正常開啟，不是 404 或 500。
        self.assertEqual(response.status_code, 200) 
      
        #確認 View 使用正確的 Template。assertTemplateUsed:確認使用哪個 Template。
        self.assertTemplateUsed(response, "analyses/overview.html") 

        #確認後端確實傳入四筆卡片資料。
        self.assertEqual(len(response.context["overview_stats"]), 4)

        #確認最後產生的 HTML 包含重要內容。assertContains:確認回傳的 HTML 是否包含指定文字。
        self.assertContains(response, "歡迎回來，創作者！")
        self.assertContains(response, "已分析影片")