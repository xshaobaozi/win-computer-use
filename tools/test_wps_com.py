"""验证 WPS 的 COM 自动化通道是否可用，并保持文档打开以便同时探测 UIA。

COM 是 WPS/Office 的"官方 API 通道"：不点界面、不看屏幕，
直接读写文档对象模型，比模拟鼠标键盘可靠几个数量级。
"""
import sys
import time

import win32com.client as win32

PROGIDS = ["Word.Application", "Kwps.Application"]

app = None
used = None
for pid in PROGIDS:
    try:
        app = win32.Dispatch(pid)
        used = pid
        break
    except Exception as e:
        print(f"{pid} 不可用: {e}")

if app is None:
    print("COM 通道不可用")
    sys.exit(1)

print(f"已连接: {used}")
print(f"应用名: {app.Name}  版本: {app.Version}")

try:
    app.Visible = True
except Exception:
    pass

doc = app.Documents.Add()
doc.Content.Text = "季度销售汇总\n客户：杭州云图\n金额：12800\n"
print(f"文档已创建，段落数={doc.Paragraphs.Count}")

# 读回验证：这就是"知道文档当前内容"的完美方式
print("--- 读回内容 ---")
print(doc.Content.Text)

# 顺便测试格式化与定位能力
doc.Paragraphs(1).Range.Bold = True
print(f"写入并加粗完成，文档名={doc.Name}")

# 保持打开 25 秒，供外部探测 UIA 树
print("保持打开 25 秒...")
time.sleep(25)

doc.Close(False)
app.Quit()
print("已关闭，未保存")
