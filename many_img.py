import asyncio
import json
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from urllib.parse import urlparse
import re
from bs4 import BeautifulSoup

# ════════════════════════════════════════════════════════════════
#  HTML / JSON PARSING (tĩnh)
# ════════════════════════════════════════════════════════════════

def get_caption_by_matching_url(all_json_data: list, image_url: str, post_caption: str = "") -> str:
    """
    Tìm caption bằng cách trích xuất Photo ID từ URL và quét toàn bộ cây JSON.
    Cách này vượt qua được việc Facebook thay đổi độ phân giải ảnh trên UI.
    """
    if not image_url:
        return ""

    # 1. Trích xuất các chuỗi số dài (thường là Photo ID) từ URL
    # VD URL: .../434654321_1681729503186316_123456789_n.jpg
    # Sẽ lấy ra được ['434654321', '1681729503186316', '123456789']
    id_tokens = re.findall(r'\d{8,}', image_url)
    
    # Fallback nếu URL có cấu trúc dị, không có số
    if not id_tokens:
        filename = urlparse(image_url).path.split('/')[-1]
        core_name = re.sub(r'_[a-zA-Z]\.jpg$', '', filename)
        id_tokens = [core_name]

    candidates = []

    def is_token_in_node(node):
        """Kiểm tra xem node này hoặc con trực tiếp của nó có chứa Photo ID không"""
        if isinstance(node, dict):
            # Cấp 1 (VD: node['id'] == '1681729503186316')
            for v in node.values():
                if isinstance(v, str) and any(t in v for t in id_tokens):
                    return True
                # Cấp 2 (VD: node['image']['uri'] == 'https://...')
                if isinstance(v, dict):
                    for sub_v in v.values():
                        if isinstance(sub_v, str) and any(t in sub_v for t in id_tokens):
                            return True
        return False

    def walk(node):
        # Đệ quy duyệt list
        if isinstance(node, list):
            for item in node:
                walk(item)
        # Đệ quy duyệt dict
        elif isinstance(node, dict):
            # Bắt trúng dict chứa ID ảnh của chúng ta
            if is_token_in_node(node):
                candidate = ""
                # Lấy message / caption
                if "message" in node and isinstance(node["message"], dict):
                    candidate = node["message"].get("text", "").strip()
                elif "caption" in node:
                    if isinstance(node["caption"], dict):
                        candidate = node["caption"].get("text", "").strip()
                    elif isinstance(node["caption"], str):
                        candidate = node["caption"].strip()
                
                # Nếu có nội dung, lưu vào danh sách chờ (không return vội)
                if candidate and len(candidate) >= 3:
                    candidates.append(candidate)
            
            # Tiếp tục đào sâu xuống dưới
            for v in node.values():
                walk(v)

    # Quét toàn bộ bể chứa dữ liệu
    for json_blob in all_json_data:
        walk(json_blob)

    # 2. Lọc kết quả để tìm ra caption chính xác nhất
    for candidate in candidates:
        # Loại bỏ các đoạn alt-text mô tả ảnh do AI của Facebook tự tạo
        noise = ("image may contain", "may contain", "ảnh có thể chứa", "no photo description")
        if any(candidate.lower().startswith(n) for n in noise):
            continue
        
        # Loại bỏ nếu nó lấy nhầm caption của cả bài post
        if post_caption and (candidate == post_caption or candidate in post_caption or post_caption in candidate):
            continue
        
        return candidate # Trả về caption hợp lệ đầu tiên

    return ""

def extract_text_from_inline_json(html: str) -> dict:
    """Phân tích HTML tĩnh để lấy caption bài viết và ảnh đầu tiên."""
    result = {"caption": "", "images": []}

    post_images  = []
    other_images = []

    script_jsons = re.findall(
        r'<script[^>]*>\s*(\{(?:[^<]|<(?!/script))*?\})\s*</script>',
        html, re.DOTALL
    )
    inline_data = re.findall(
        r'handleWithCustomApplyEach\s*\(\s*ScheduledApplyEach\s*,\s*(\{.*?\})\s*\)',
        html, re.DOTALL
    )

    def walk(node, depth=0):
        if depth > 30 or not node:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return

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

        for img_key in ["large_media_preview_image", "photo_image"]:
            if img_key in node:
                val = node[img_key]
                uri = ""
                if isinstance(val, dict):
                    uri = val.get("uri") or val.get("url", "")
                elif isinstance(val, str):
                    uri = val
                if uri and uri.startswith("http") and uri not in post_images:
                    post_images.append(uri)

        for img_key in ["full_picture", "preferred_image", "image"]:
            if img_key in node:
                val = node[img_key]
                uri = ""
                if isinstance(val, dict):
                    uri = val.get("uri") or val.get("url", "")
                elif isinstance(val, str):
                    uri = val
                if uri and uri.startswith("http") and uri not in other_images:
                    other_images.append(uri)

        for v in node.values():
            walk(v, depth + 1)

    for blob in script_jsons + inline_data:
        try:
            data = json.loads(blob)
            walk(data)
            if result["caption"]:
                break
        except Exception:
            pass

    if not result["caption"]:
        for regex in [
            r'"message"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"',
            r'"body"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"',
        ]:
            m = re.search(regex, html)
            if m:
                try:
                    result["caption"] = m.group(1).encode().decode(
                        "unicode_escape", errors="replace"
                    )
                except Exception:
                    result["caption"] = m.group(1)
                break

    if post_images:
        result["images"] = post_images
    elif other_images:
        n = len(other_images)
        if n <= 3:
            result["images"] = [other_images[-1]]
        else:
            result["images"] = [other_images[i] for i in range(2, n, 3)]
            if not result["images"]:
                result["images"] = [other_images[-1]]

    return result


def extract_current_slide_image(html: str) -> str:
    """Fallback: lấy URL ảnh hiện tại từ HTML tĩnh."""
    candidates = []
    img_tags = re.findall(
        r'<img[^>]+src="(https://[^"]+(?:scontent|fbcdn)[^"]+)"[^>]*>',
        html
    )
    for src in img_tags:
        if any(x in src for x in ['_n.jpg', '_o.jpg', '_b.jpg', 'p720x720', 'p960x960',
                                   'p1080x1080', 's1500x1500', 's720x720', 's960x960']):
            if src not in candidates:
                candidates.append(src)
    if candidates:
        return candidates[0]

    for pattern in [
        r'"large_media_preview_image"\s*:\s*\{[^}]*"uri"\s*:\s*"(https://[^"]+)"',
        r'"photo_image"\s*:\s*\{[^}]*"uri"\s*:\s*"(https://[^"]+)"',
        r'"preferred_image"\s*:\s*\{[^}]*"uri"\s*:\s*"(https://[^"]+)"',
    ]:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return ""


# ════════════════════════════════════════════════════════════════
#  [MỚI] EXTRACT CAPTION RIÊNG TỪNG ẢNH TỪ XHR RESPONSE
# ════════════════════════════════════════════════════════════════

def _extract_photo_caption_from_node(node: dict) -> str:
    """
    Tìm caption riêng của một Photo node trong GraphQL response.

    Facebook trả về các trường theo thứ tự ưu tiên:
      1. node["message"]["text"]         – caption người dùng nhập cho từng ảnh
      2. node["accessibility_caption"]   – mô tả alt tự động (thường là "may contain…")
      3. node["caption"]["text"]         – một số API version dùng trường này

    Chỉ chấp nhận trường (1) và (3) vì (2) thường là AI-generated noise.
    """
    if not isinstance(node, dict):
        return ""

    # Ưu tiên cao nhất: message.text của Photo node
    msg = node.get("message")
    if isinstance(msg, dict):
        text = msg.get("text", "").strip()
        if text and len(text) >= 3:
            return text

    # Trường caption (một số API version)
    cap = node.get("caption")
    if isinstance(cap, dict):
        text = cap.get("text", "").strip()
        if text and len(text) >= 3:
            return text
    elif isinstance(cap, str) and len(cap.strip()) >= 3:
        return cap.strip()

    return ""

def extract_photo_caption_from_xhr(response_body, post_caption: str = "", seen_captions: set | None = None) -> str:
    """Thêm biến seen_captions để bỏ qua các caption của slide trước."""
    if seen_captions is None:
        seen_captions = set()

    def _is_ai_alt_text(text: str) -> bool:
        noise_prefixes = (
            "image may contain", "photo may contain", "may contain:",
            "ảnh có thể chứa", "có thể chứa:", "no photo description available",
            "no description available",
        )
        return any(text.lower().strip().startswith(p) for p in noise_prefixes)

    def _is_same_as_post(text: str) -> bool:
        if not post_caption: return False
        t, p = text.strip(), post_caption.strip()
        return t == p or t in p or p in t

    def walk(node, depth=0) -> str:
        if depth > 40 or not node: return ""
        if isinstance(node, list):
            for item in node:
                found = walk(item, depth + 1)
                if found: return found
            return ""
        if not isinstance(node, dict): return ""

        typename = node.get("__typename", "")
        if typename in ("Photo", "Video", "StoryAttachment"):
            candidate = _extract_photo_caption_from_node(node)
            # Kiểm tra thêm điều kiện: candidate chưa từng xuất hiện ở các ảnh trước
            if (candidate and not _is_ai_alt_text(candidate) 
                and not _is_same_as_post(candidate) 
                and candidate not in seen_captions):
                return candidate

        msg = node.get("message")
        if isinstance(msg, dict):
            text = msg.get("text", "").strip()
            if (text and len(text) >= 3 and not _is_ai_alt_text(text) 
                and not _is_same_as_post(text) 
                and text not in seen_captions): # Kiểm tra seen_captions
                parent_hints = {"photo_id", "fbid", "media_id", "node_id", "image", "photo", "media"}
                if parent_hints & set(node.keys()):
                    return text

        for v in node.values():
            found = walk(v, depth + 1)
            if found: return found
        return ""

    return walk(response_body)
# ════════════════════════════════════════════════════════════════
#  DOM LIVE – LẤY ẢNH + CAPTION TỪNG SLIDE (DOM fallback)
# ════════════════════════════════════════════════════════════════

async def get_visible_image_url(page) -> str:
    """Lấy src ảnh đang hiển thị lớn nhất trong viewer."""
    url = await page.evaluate("""() => {
        const selectors = [
            'div[data-pagelet="MediaViewerPhoto"] img',
            'div[role="dialog"] img[src*="scontent"]',
            'div[role="dialog"] img[src*="fbcdn"]',
            'img[data-visualcompletion="media-vc-image"]',
            '[aria-label*="photo"] img[src*="scontent"]',
            '[aria-label*="ảnh"] img[src*="scontent"]',
        ];
        for (const sel of selectors) {
            const imgs = Array.from(document.querySelectorAll(sel));
            const visible = imgs.filter(img => {
                const r = img.getBoundingClientRect();
                return r.width > 100 && r.height > 100;
            });
            if (visible.length > 0) {
                visible.sort((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    return (rb.width * rb.height) - (ra.width * ra.height);
                });
                return visible[0].src || visible[0].getAttribute('src') || '';
            }
        }
        const allImgs = Array.from(document.querySelectorAll(
            'img[src*="scontent"], img[src*="fbcdn"]'
        ));
        const big = allImgs.filter(img => {
            const r = img.getBoundingClientRect();
            return r.width > 200 && r.height > 200;
        });
        if (big.length > 0) {
            big.sort((a, b) => {
                const ra = a.getBoundingClientRect();
                const rb = b.getBoundingClientRect();
                return (rb.width * rb.height) - (ra.width * ra.height);
            });
            return big[0].src || '';
        }
        return '';
    }""")
    return url or ""


async def get_slide_caption_from_dom(page, post_caption: str, seen_captions: set) -> str:
    """
    Phiên bản XPath: Trực tiếp truy xuất vào vị trí thẻ HTML theo đường dẫn tuyệt đối.
    """
    # Đường dẫn XPath bạn cung cấp
    TARGET_XPATH = "/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div[2]/div/div[1]/div/div[1]/div[2]/div[1]/div[2]/span"
    
    try:
        # Playwright nhận diện XPath khi có tiền tố xpath=
        locator = page.locator(f"xpath={TARGET_XPATH}").first
        
        # Kiểm tra xem phần tử có tồn tại trên màn hình lúc này không
        if await locator.count() > 0:
            raw_text = await locator.inner_text()
            raw_text = raw_text.strip() if raw_text else ""
        else:
            print("    [Debug DOM] XPath bị trượt: Không tìm thấy phần tử nào tại đường dẫn này.")
            return ""
            
    except Exception as e:
        print(f"    [Debug DOM] Lỗi khi trích xuất bằng XPath: {e}")
        return ""

    if not raw_text:
        return ""

    # ==============================================================================
    # 🛡️ VẪN GIỮ LỚP KIỂM TRA ĐỀ PHÒNG DOM UPDATE CHẬM HAY TRÙNG LẶP
    # ==============================================================================
    
    # 1. Kiểm tra xem text lấy được có bị trùng với caption của cả bài post không
    if post_caption and (raw_text == post_caption or raw_text in post_caption or post_caption in raw_text):
        print("    -> [Bỏ qua] Text lấy được lại trùng với caption bài post chung.")
        return ""

    # 2. Kiểm tra xem do FB load chậm nên vẫn đang dính caption của ảnh cũ không
    if raw_text in seen_captions:
        print("    -> [Bỏ qua] Text đã xuất hiện ở slide trước (DOM chưa update kịp).")
        return ""

    # Chốt đơn
    return raw_text#  ĐIỀU HƯỚNG CAROUSEL
# ════════════════════════════════════════════════════════════════

async def click_next_button(page) -> bool:
    """Click nút next. Thử 3 chiến lược, trả về True nếu thành công."""
    next_labels = [
        "Next photo", "Ảnh tiếp theo", "Next", "Tiếp theo",
        "Go to next item", "Next slide",
    ]
    for label in next_labels:
        try:
            btn = page.locator(f'[aria-label="{label}"]').first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                return True
        except Exception:
            pass

    try:
        await page.keyboard.press("ArrowRight")
        return True
    except Exception:
        pass

    clicked = await page.evaluate("""() => {
        const buttons = Array.from(document.querySelectorAll('[role="button"]'));
        const btn = buttons.find(b => {
            const r = b.getBoundingClientRect();
            const label = (b.getAttribute('aria-label') || '').toLowerCase();
            const txt   = (b.textContent || '').trim();
            return r.left > window.innerWidth * 0.55
                && r.width > 20 && r.width < 200 && r.height > 20
                && (label.includes('next') || label.includes('tiếp') ||
                    label.includes('right') || txt === '›' || txt === '❯' || r.width < 80);
        });
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    return bool(clicked)


async def is_carousel_post(page) -> bool:
    """Kiểm tra bài post có nhiều ảnh dạng carousel không."""
    has_next = await page.evaluate("""() => {
        const labels = ['Next photo', 'Ảnh tiếp theo', 'Next', 'Tiếp theo',
                        'Go to next item', 'Next slide'];
        for (const label of labels) {
            const el = document.querySelector(`[aria-label="${label}"]`);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 || r.height > 0) return true;
            }
        }
        return false;
    }""")
    return bool(has_next)


# ════════════════════════════════════════════════════════════════
#  [MỚI] INTERCEPT XHR KHI NAVIGATE SLIDES
# ════════════════════════════════════════════════════════════════

def make_xhr_collector():
    """
    Tạo một collector để bắt XHR responses trong khoảng thời gian nhất định.

    Trả về:
      - collector list (append-able)
      - async handler để đăng ký vào page.on("response", ...)
    """
    collected: list = []

    async def handler(response):
        content_type = response.headers.get("content-type", "")
        url = response.url
        # Chỉ lấy JSON từ các endpoint GraphQL của Facebook
        if response.status != 200:
            return
        if "json" not in content_type and "javascript" not in content_type:
            return
        # Endpoint thường dùng: graphql, api/graphql, ajax/bz?, ...
        is_graphql = any(kw in url for kw in [
            "graphql", "api/graphql", "ajax/bz", "api/?", "stories/composer"
        ])
        if not is_graphql:
            return
        try:
            body = await response.json()
            collected.append(body)
        except Exception:
            pass

    return collected, handler


async def get_caption_for_current_slide_via_xhr(xhr_responses: list, post_caption: str, seen_captions: set) -> str:
    """
    Duyệt ngược (từ mới nhất đến cũ nhất) danh sách XHR.
    """
    for resp in reversed(xhr_responses):
        cap = extract_photo_caption_from_xhr(resp, post_caption, seen_captions)
        if cap:
            return cap
    return ""

# ════════════════════════════════════════════════════════════════
#  [MỚI] LẤY CAPTION SLIDE ĐẦU TIÊN TỪ HTML TĨNH
# ════════════════════════════════════════════════════════════════

def extract_first_slide_caption_from_html(html: str, post_caption: str) -> str:
    """
    Tìm caption của ảnh đầu tiên trong HTML tĩnh.

    Facebook nhúng dữ liệu từng Photo vào inline JSON với trường:
      "message": {"text": "..."}  bên trong một Photo node.

    Hàm này tìm TẤT CẢ các message.text rồi trả về cái nào
    KHÁC với post_caption (tức là caption riêng của ảnh đầu).
    """
    candidates = []

    # Regex tìm tất cả "message":{"text":"..."} trong HTML
    for m in re.finditer(
        r'"message"\s*:\s*\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)+)"',
        html
    ):
        try:
            text = m.group(1).encode().decode("unicode_escape", errors="replace").strip()
        except Exception:
            text = m.group(1).strip()

        if not text or len(text) < 3:
            continue
        if post_caption and (text == post_caption or text in post_caption or post_caption in text):
            continue
        if text not in candidates:
            candidates.append(text)

    return candidates[0] if candidates else ""


# ════════════════════════════════════════════════════════════════
#  DUYỆT TOÀN BỘ CAROUSEL (đã cải tiến)
# ════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """Bỏ query string để so sánh."""
    return url.split("?")[0] if url else ""


async def crawl_carousel_images(page, first_image_url: str, post_caption: str, html: str, all_responses: list) -> list:
    collected = []
    seen_urls = set()
    seen_captions = set()

    # 1. Rút trích toàn bộ JSON ẩn chứa trong HTML ngay từ lúc load trang
    static_jsons = []
    script_blocks = re.findall(r'<script[^>]*>\s*(\{(?:[^<]|<(?!/script))*?\})\s*</script>', html, re.DOTALL)
    for block in script_blocks:
        try:
            static_jsons.append(json.loads(block))
        except Exception:
            pass

    def get_global_jsons():
        # Gộp tất cả data tĩnh và mạng lại thành 1 "bể chứa" khổng lồ
        return static_jsons + all_responses

    # ── Slide đầu tiên ──────────────────────────────────────────
    if first_image_url:
        first_cap = get_caption_by_matching_url(get_global_jsons(), first_image_url, post_caption)
        if not first_cap:
            first_cap = await get_slide_caption_from_dom(page, post_caption, seen_captions)

        collected.append({"url": first_image_url, "caption": first_cap})
        seen_urls.add(normalize_url(first_image_url))
        if first_cap: seen_captions.add(first_cap)
        
        print(f"[+] Slide 0: ảnh OK | caption: {first_cap[:80] if first_cap else '(không có)'}")

    print("[*] Bắt đầu duyệt các slide tiếp theo…")
    max_slides = 50
    consecutive_dupes = 0
    max_consecutive_dupes = 3

    for slide_idx in range(1, max_slides + 1):
        clicked = await click_next_button(page)
        if not clicked: break

        await asyncio.sleep(1.5) # Đợi Facebook render và tải thêm XHR (nếu có)

        current_url = await get_visible_image_url(page)
        if not current_url:
            html_now = await page.content()
            current_url = extract_current_slide_image(html_now)

        if not current_url:
            consecutive_dupes += 1
            continue

        norm = normalize_url(current_url)
        if norm in seen_urls:
            consecutive_dupes += 1
        else:
            consecutive_dupes = 0
            seen_urls.add(norm)

            # SỬ DỤNG VŨ KHÍ TỐI THƯỢNG: Tìm chính xác caption của url này
            slide_caption = get_caption_by_matching_url(get_global_jsons(), current_url, post_caption)

            if not slide_caption:
                slide_caption = await get_slide_caption_from_dom(page, post_caption, seen_captions)

            collected.append({"url": current_url, "caption": slide_caption})
            if slide_caption: seen_captions.add(slide_caption)

            print(f"[+] Slide {slide_idx}: ảnh OK | caption: {slide_caption[:80] if slide_caption else '(không có)'}")

        if consecutive_dupes >= max_consecutive_dupes:
            break

    return collected
# ════════════════════════════════════════════════════════════════
#  HÀM CHÍNH
# ════════════════════════════════════════════════════════════════

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

        # Thu thập tất cả responses (để fallback caption bài viết)
        all_responses = []

        async def capture_all_responses(response):
            content_type = response.headers.get("content-type", "")
            if "json" in content_type and response.status == 200:
                try:
                    body = await response.json()
                    all_responses.append(body)
                except Exception:
                    pass

        page.on("response", capture_all_responses)

        print(f"[*] Đang mở: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)

        html = await page.content()
        print(f"[*] HTML size: {len(html):,} bytes")

        # ── Caption + ảnh từ HTML tĩnh ───────────────────────────
        result = extract_text_from_inline_json(html)

        # Fallback caption bài viết từ XHR
        if not result["caption"]:
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

        post_caption = result["caption"]
        print(f"[*] Caption bài viết: {post_caption[:100] if post_caption else '(không có)'}")

        # ── Phát hiện và xử lý carousel ─────────────────────────
        has_carousel = await is_carousel_post(page)

        if has_carousel:
            print("[*] Bài viết có carousel ảnh.")
            first_img = await get_visible_image_url(page)
            if not first_img and result["images"]:
                first_img = result["images"][0]

            # Cập nhật lời gọi hàm ở dòng này: thêm all_responses
            carousel_items = await crawl_carousel_images(
                page, first_img, post_caption, html, all_responses
            )
            if carousel_items:
                result["images"] = carousel_items
                print(f"[*] Carousel: lấy được {len(carousel_items)} ảnh.")
        else:
            print("[*] Bài viết đơn ảnh hoặc không có carousel.")
            result["images"] = [
                {"url": img, "caption": ""} for img in result["images"]
            ]

        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)

        await context.close()

    # ── In kết quả ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    if result["caption"]:
        print(f"✅ Caption bài viết:\n{result['caption']}")
    else:
        print("❌ Không lấy được caption bài viết")

    if result["images"]:
        print(f"\n✅ {len(result['images'])} ảnh:")
        for i, item in enumerate(result["images"], 1):
            print(f"\n  [{i}] {item['url']}")
            if item.get("caption"):
                print(f"       Caption ảnh: {item['caption']}")
            else:
                print(f"       Caption ảnh: (không có)")
    else:
        print("❌ Không lấy được ảnh")

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    asyncio.run(crawl_fb_post(
        "https://www.facebook.com/photo/?fbid=4011384602486914&set=pcb.2228645754659195"
    ))