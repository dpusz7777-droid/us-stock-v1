# -*- coding: utf-8 -*-
"""
基于截图的 uSMART 持仓表格 OCR 脚本

说明：
- 使用 pyautogui 从屏幕上截取指定区域
- 进行灰度 + 二值化预处理，提升 OCR 精度
- 支持 EasyOCR 或 Tesseract 两种引擎
- 精准提取“股票代码”和“持仓金额”，并输出 JSON
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyautogui
from PIL import Image, ImageOps, ImageFilter

try:
    import cv2
except ImportError:
    cv2 = None


def parse_region(region_str):
    parts = [p.strip() for p in region_str.split(",")]
    if len(parts) != 4:
        raise ValueError("region 必须是 left,top,width,height")
    return tuple(int(float(x)) for x in parts)


def ask_region():
    input("将鼠标移动到 ECO/SPCX 所在行区域的左上角，然后按 Enter：")
    x1, y1 = pyautogui.position()
    print(f"左上角：({x1}, {y1})")
    input("将鼠标移动到 ECO/SPCX 所在行区域的右下角，然后按 Enter：")
    x2, y2 = pyautogui.position()
    print(f"右下角：({x2}, {y2})")
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    print(f"选定的 ECO/SPCX 区域：left={left}, top={top}, width={width}, height={height}")
    return left, top, width, height


def preprocess_image(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    sharp = gray.filter(ImageFilter.SHARPEN)
    if cv2 is not None:
        arr = np.array(sharp)
        arr = cv2.GaussianBlur(arr, (3, 3), 0)
        _, thresh = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return Image.fromarray(thresh)
    threshold = 160
    return sharp.point(lambda p: 255 if p > threshold else 0)


def ocr_easyocr(reader, img):
    img_np = np.array(img)
    results = reader.readtext(img_np, detail=1, paragraph=False)
    return [{"bbox": bbox, "text": text, "conf": float(conf)} for bbox, text, conf in results]


def ocr_tesseract(pytesseract, img):
    try:
        data = pytesseract.image_to_data(img, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
    except AttributeError:
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [{"bbox": [[0, 0], [0, 0], [0, 0], [0, 0]], "text": line, "conf": None} for line in lines]

    parsed = []
    n = len(data.get("text", []))
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        bbox = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        parsed.append({"bbox": bbox, "text": text, "conf": None})
    return parsed


def normalize_text(text: str) -> str:
    return text.replace("：", ":").replace("，", ",").replace("\u3000", " ").strip()


def group_words_to_rows(parsed, y_thresh=20):
    rows = []
    for item in parsed:
        text = normalize_text(item["text"])
        bbox = item.get("bbox")
        if not bbox:
            continue
        y = (bbox[0][1] + bbox[2][1]) / 2
        placed = False
        for row in rows:
            if abs(row["y"] - y) <= y_thresh:
                row["texts"].append(text)
                row["bboxes"].append(bbox)
                row["y"] = (row["y"] * len(row["texts"]) + y) / (len(row["texts"]) + 1)
                placed = True
                break
        if not placed:
            rows.append({"y": y, "texts": [text], "bboxes": [bbox]})
    return sorted(rows, key=lambda x: x["y"])


def extract_holdings(parsed, targets=None, offset=(0, 0)):
    if targets is None:
        targets = ["ECO", "SPCX"]

    rows = group_words_to_rows(parsed)
    holdings = []
    pattern_code = re.compile(r"\b([A-Z]{2,6})\b")
    pattern_amount = re.compile(r"([+-]?\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?|\d+\.\d+)")
    for row in rows:
        line = " ".join(row["texts"])
        line = re.sub(r"\s+", " ", line)
        if not any(target in line for target in targets):
            continue
        codes = pattern_code.findall(line)
        amounts = pattern_amount.findall(line)
        if not codes and not amounts:
            continue
        left = min(pt[0] for bbox in row["bboxes"] for pt in bbox)
        right = max(pt[0] for bbox in row["bboxes"] for pt in bbox)
        top = min(pt[1] for bbox in row["bboxes"] for pt in bbox)
        bottom = max(pt[1] for bbox in row["bboxes"] for pt in bbox)
        abs_left = left + offset[0]
        abs_top = top + offset[1]
        abs_right = right + offset[0]
        abs_bottom = bottom + offset[1]
        holdings.append({
            "股票代码": codes[0] if codes else None,
            "持仓金额": amounts[0] if amounts else None,
            "bbox": [abs_left, abs_top, abs_right, abs_bottom],
            "raw": line,
        })
    return holdings


def main():
    parser = argparse.ArgumentParser(description="基于屏幕截取的 uSMART 持仓 OCR")
    parser.add_argument("--engine", choices=["easyocr", "tesseract"], default="easyocr")
    parser.add_argument("--interval", type=float, default=2.0, help="循环截图间隔秒数")
    parser.add_argument("--out", default="usmart_holdings.json", help="输出 JSON 文件")
    parser.add_argument("--region", type=str, default=None, help="可选：left,top,width,height，跳过交互选择")
    parser.add_argument("--full-screen", action="store_true", help="截取全屏并自动定位 ECO/SPCX 行")
    parser.add_argument("--image-path", type=str, default=None, help="从图片文件识别，而不是截屏")
    args = parser.parse_args()

    print("===== uSMART 持仓 OCR =====")
    if args.image_path:
        print(f"使用图片文件：{args.image_path}")
        screenshot = Image.open(args.image_path)
        region = None
    elif args.full_screen:
        print("使用全屏截图，自动定位 ECO/SPCX 行")
        screen_size = pyautogui.size()
        region = (0, 0, screen_size.width, screen_size.height)
    elif args.region:
        region = parse_region(args.region)
        print(f"使用指定区域：{region}")
    else:
        print("请直接选择表格区域。只识别该区域，不扫描整张屏幕。")
        region = ask_region()

    if args.engine == "easyocr":
        try:
            import easyocr
        except ImportError:
            print("请先安装 easyocr：pip install easyocr")
            sys.exit(1)
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        ocr_fn = lambda im: ocr_easyocr(reader, im)
    else:
        try:
            import pytesseract
        except ImportError:
            print("请先安装 pytesseract：pip install pytesseract")
            sys.exit(1)
        ocr_fn = lambda im: ocr_tesseract(pytesseract, im)

    print("按 Ctrl+C 停止。正在开始循环识别...")
    while True:
        if args.image_path:
            cropped = screenshot
            offset = (0, 0)
        else:
            left, top, width, height = region
            cropped = pyautogui.screenshot(region=(left, top, width, height))
            offset = (left, top)
        preprocessed = preprocess_image(cropped)
        parsed = ocr_fn(preprocessed)
        holdings = extract_holdings(parsed, offset=offset)
        result = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "region": {
                "left": offset[0],
                "top": offset[1],
                "width": cropped.width,
                "height": cropped.height,
            },
            "holdings": holdings,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if args.image_path:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
