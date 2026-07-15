"""
图片 OCR 公共服务 — 基于 PaddleOCR Layout Parsing API
"""
import base64
import requests

_OCR_API_URL = "https://8e5ff1q6gbiaf5i0.aistudio-app.com/layout-parsing"
_OCR_TOKEN   = "0c245f042b17cb6b1573a45e477361c074f88d0e"


def ocr_image_to_markdown(img_bytes: bytes, timeout: int = 60) -> str:
    """
    把图片 OCR 成 markdown 文本。
    抛 ValueError 如果识别失败或图片过大。
    """
    if len(img_bytes) > 20 * 1024 * 1024:
        raise ValueError("图片太大，请压缩后上传（限制 20MB）")

    img_b64 = base64.standard_b64encode(img_bytes).decode("ascii")
    headers = {
        "Authorization": f"token {_OCR_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "file":                      img_b64,
        "fileType":                  1,
        "useDocOrientationClassify": False,
        "useDocUnwarping":           False,
        "useChartRecognition":       False,
    }

    try:
        resp = requests.post(_OCR_API_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise ValueError(f"OCR 请求失败：{e}")

    blocks = data.get("result", {}).get("layoutParsingResults", [])
    md_parts = []
    for b in blocks:
        text = b.get("markdown", {}).get("text", "")
        if text:
            md_parts.append(text)
    full_md = "\n".join(md_parts).strip()

    if not full_md:
        raise ValueError("OCR 未识别到文字，请确认图片清晰")

    return full_md
