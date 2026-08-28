from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .services.youtube_url_parser import (
    InvalidYouTubeUrlError,
    get_video_id_from_youtube_url,
)

class NewAnalysisForm(forms.Form):
    """新增分析時使用的影片網址表單。"""

    input_video_url = forms.URLField( #資料層：驗證、錯誤、cleaned_data
        label=_("YouTube 影片網址"),
        help_text=_("請貼上公開的 YouTube 影片網址。"),
        widget=forms.URLInput( #顯示層：產生 <input type="url">，也就是widget 和 attrs 主要負責「HTML 怎麼產生」，
            attrs={
                "class": "mt-2 block w-full rounded-xl border border-app-border bg-white px-4 py-3 text-base text-brand-navy outline-none transition placeholder:text-slate-400 focus:border-brand-purple focus:ring-2 focus:ring-violet-200 aria-invalid:border-red-600 aria-invalid:bg-red-50 aria-invalid:focus:border-red-600 aria-invalid:focus:ring-red-200",
                "placeholder": "https://www.youtube.com/watch?v=...",
                "autocomplete": "url",
            }
        ),
    )

    #clean() 是 Django Form 規定的「整份表單驗證入口」。clean()名稱是 Django 框架的固定慣例
    def clean(self):
      """這裡的clean()主要是驗證 YouTube 網址並加入解析後的影片ID。流程如下：
          瀏覽器送出 POST
            ↓
          URLField 先驗證基本網址格式
                  ↓
          執行 NewAnalysisForm.clean()
                  ↓
          執行我們的 YouTube 網址驗證
                  ↓
          產生 cleaned_data 或 errors
      """

      validated_form_data = super().clean() #代表 NewAnalysisForm 繼承 Django 的 forms.Form，而super() 表示取得父類別，也就是 Django 的 Form；因此：super().clean()意思是：先執行 Django Form 原本的 clean()，取得 Django 已完成基本驗證的資料。
      input_video_url = validated_form_data.get("input_video_url")

      if input_video_url is None:
          return validated_form_data

      try:
          youtube_video_id = get_video_id_from_youtube_url(input_video_url)
          
      except InvalidYouTubeUrlError:
          self.add_error(
              "input_video_url",
              ValidationError(_("請輸入支援的 YouTube 影片網址。"),code="invalid_youtube_url"),
          )
      else:
          validated_form_data["youtube_video_id"] = youtube_video_id

      return validated_form_data
