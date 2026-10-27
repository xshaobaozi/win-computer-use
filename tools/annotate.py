"""把 OCR 识别结果画回截图上，用于验证识别与定位精度。

输出 annotated.png：每个识别到的文本元素画框 + 编号，指定目标画准星。
"""
import sys

from PIL import ImageDraw, ImageFont

import vision_snapshot as vs

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "账号登录"
    target = sys.argv[2] if len(sys.argv) > 2 else "更多"

    hwnd = vs.find_hwnd(kw)
    if not hwnd:
        print("找不到窗口")
        return
    img, origin = vs.capture(hwnd)
    elems = vs.ocr_elements(img, origin)
    ox, oy = origin

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 14)
    small = ImageFont.truetype(FONT_PATH, 12)

    for e in elems:
        x, y, w, h = e["box"]
        x, y = x - ox, y - oy  # 屏幕坐标转回图像坐标
        draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=(230, 60, 60), width=2)
        label = str(e["id"])
        tw = draw.textlength(label, font=small)
        draw.rectangle([x - 2, y - 18, x - 2 + tw + 6, y - 2], fill=(230, 60, 60))
        draw.text((x + 1, y - 17), label, font=small, fill=(255, 255, 255))

    # 目标元素画准星，直观展示点击落点
    cands = [e for e in elems if target in e["text"]]
    if cands:
        best = max(cands, key=lambda e: e["conf"])
        x, y, w, h = best["box"]
        cx, cy = x - ox + w // 2, y - oy + h // 2
        r = 14
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(30, 160, 90), width=2)
        draw.line([cx - r - 8, cy, cx - 4, cy], fill=(30, 160, 90), width=2)
        draw.line([cx + 4, cy, cx + r + 8, cy], fill=(30, 160, 90), width=2)
        draw.line([cx, cy - r - 8, cx, cy - 4], fill=(30, 160, 90), width=2)
        draw.line([cx, cy + 4, cx, cy + r + 8], fill=(30, 160, 90), width=2)
        draw.text((cx - 40, cy + r + 6), f"({x + w // 2},{y + h // 2})",
                  font=small, fill=(30, 120, 70))

    # 底部说明条
    bar_h = 26
    canvas = ImageDraw.Draw(img)
    canvas.rectangle([0, img.height - bar_h, img.width, img.height], fill=(255, 255, 255))
    canvas.text((8, img.height - bar_h + 5),
                f"识别 {len(elems)} 个元素  |  来源: OCR  |  窗口 {img.width}x{img.height}",
                font=small, fill=(90, 90, 90))

    img.save("annotated.png")
    print(f"已生成 annotated.png，共标注 {len(elems)} 个元素")


if __name__ == "__main__":
    main()
