import asyncio
import json
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


def extract_text_from_inline_json(html: str) -> dict:
    result = {"caption": "", "images": []}

    script_jsons = re.findall(
        r'<script[^>]*>\s*(\{(?:[^<]|<(?!/script))*?\})\s*</script>',
        html, re.DOTALL
    )
    inline_data = re.findall(
        r'handleWithCustomApplyEach\s*\(\s*ScheduledApplyEach\s*,\s*(\{.*?\})\s*\)',
        html, re.DOTALL
    )
    all_candidates = script_jsons + inline_data

    def walk(node, depth=0):
        if depth > 30 or not node:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return

        # Tìm caption
        if "message" in node and isinstance(node["message"], dict):
            text = node["message"].get("text", "").strip()
            if text and len(text) > 10 and not result["caption"]:
                result["caption"] = text

        if not result["caption"]:
            for key in ["body", "comet_sections"]:
                if key in node and isinstance(node[key], dict):
                    msg = node[key].get("message", {})
                    if isinstance(msg, dict) and msg.get("text"):
                        result["caption"] = msg["text"].strip()

        # Tìm ảnh — giữ nguyên logic cũ, thu thập tất cả
        for img_key in ["image", "large_media_preview_image", "full_picture",
                        "preferred_image", "photo_image"]:
            if img_key in node:
                val = node[img_key]
                if isinstance(val, dict):
                    uri = val.get("uri") or val.get("url", "")
                    if uri and uri.startswith("http") and uri not in result["images"]:
                        result["images"].append(uri)
                elif isinstance(val, str) and val.startswith("http"):
                    if val not in result["images"]:
                        result["images"].append(val)

        for v in node.values():
            walk(v, depth + 1)

    for blob in all_candidates:
        try:
            data = json.loads(blob)
            walk(data)
            if result["caption"]:
                break
        except Exception:
            pass

    if not result["caption"]:
        m = re.search(r'"message"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"', html)
        if m:
            result["caption"] = m.group(1).encode().decode("unicode_escape", errors="replace")
        if not result["caption"]:
            m = re.search(r'"body"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"', html)
            if m:
                result["caption"] = m.group(1)

    # ✅ CHỖ DUY NHẤT THAY ĐỔI: chỉ giữ lại ảnh cuối cùng
    # Vì walk duyệt DFS: avatar → thumbnail → ảnh post gốc (luôn ở cuối)
    if result["images"]:
        result["images"] = [result["images"][-1]]

    return result


async def crawl_fb_post(url: str):
    user_data_dir = "./facebook_profile"

    async with Stealth().use_async(async_playwright()) as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 720},
            args=["--lang=vi-VN,vi"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        all_responses = []

        async def capture_response(response):
            content_type = response.headers.get("content-type", "")
            if "json" in content_type and response.status == 200:
                try:
                    body = await response.json()
                    all_responses.append(body)
                except Exception:
                    pass

        page.on("response", capture_response)

        print(f"[*] Đang mở: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)

        html = await page.content()
        print(f"[*] HTML size: {len(html):,} bytes")

        result = extract_text_from_inline_json(html)

        if not result["caption"]:
            print("[*] Không tìm thấy trong HTML, thử JSON responses...")
            def walk_responses(node, depth=0):
                if depth > 30 or not node:
                    return
                if isinstance(node, list):
                    for i in node:
                        walk_responses(i, depth + 1)
                    return
                if not isinstance(node, dict):
                    return
                if "message" in node and isinstance(node.get("message"), dict):
                    text = node["message"].get("text", "").strip()
                    if text and len(text) > 10 and not result["caption"]:
                        result["caption"] = text
                for v in node.values():
                    walk_responses(v, depth + 1)

            for resp in all_responses:
                walk_responses(resp)
                if result["caption"]:
                    break

        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)

        await context.close()

    print("\n" + "=" * 60)
    if result["caption"]:
        print(f"✅ Caption:\n{result['caption']}")
    else:
        print("❌ Không lấy được caption")

    if result["images"]:
        print(f"\n✅ Ảnh post:\n   {result['images'][0]}")
    else:
        print("❌ Không lấy được ảnh")

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    asyncio.run(crawl_fb_post("https://www.facebook.com/share/p/1AXVrtgXjv/"))