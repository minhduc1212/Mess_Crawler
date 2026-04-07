import asyncio
import re
import json
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


# ─────────────────────────────────────────────
#  REGEX helpers
# ─────────────────────────────────────────────

# Khớp giờ dạng H:MM hoặc HH:MM  (00:00 – 23:59)
TIME_RE = re.compile(r'\b([01]?\d|2[0-3]):[0-5]\d\b')

# Khớp các dạng ngày tiếng Việt thường gặp trên Facebook:
#   - "Hôm nay", "Hôm qua"
#   - "Thứ Hai" … "Thứ Bảy", "Chủ Nhật"
#   - "12 Tháng 3", "12 tháng 3 năm 2024"
#   - "12/3/2024", "12/03/2024"
DATE_RE = re.compile(
    r'(?:'
    r'Hôm\s+(?:nay|qua)'
    r'|Thứ\s+(?:Hai|Ba|Tư|Năm|Sáu|Bảy)'
    r'|Chủ\s+Nhật'
    r'|\d{1,2}\s+[Tt]háng\s+\d{1,2}(?:\s+(?:năm\s+)?\d{4})?'
    r'|\d{1,2}/\d{1,2}/\d{4}'
    r')',
    re.IGNORECASE,
)


def parse_divider_text(text: str):
    """
    Nếu `text` là nội dung của một divider ngăn cách,
    trả về (date_str | None, time_str | None).
    Nếu không tìm thấy giờ → trả về (None, None).
    """
    time_m = TIME_RE.search(text)
    if not time_m:
        return None, None

    time_str = time_m.group(0)
    date_m = DATE_RE.search(text)
    date_str = date_m.group(0).strip() if date_m else None
    return date_str, time_str


def is_divider_row(row_text: str, has_sender: bool, has_message: bool) -> bool:
    """
    Một row được coi là divider (chứa mốc thời gian) khi:
      - Có pattern giờ (xx:xx)
      - Không có sender (h5) VÀ không có nội dung tin nhắn thật
    """
    return (not has_sender) and (not has_message) and bool(TIME_RE.search(row_text))


# ─────────────────────────────────────────────
#  Thu thập tin nhắn từ DOM hiện tại
# ─────────────────────────────────────────────

async def collect_messages(page, chat_data: list, seen_keys: set) -> int:
    """
    Quét toàn bộ div[role="row"] hiện có trong DOM.
    - Divider → cập nhật current_date / current_time
    - Tin nhắn thật → gán timestamp, kiểm tra trùng rồi prepend vào chat_data

    Trả về số tin nhắn MỚI được thêm vào lần này.
    """
    rows = await page.query_selector_all('div[role="row"]')

    current_date: str | None = None
    current_time: str = "Chưa rõ"
    new_msgs: list = []   # tin nhắn mới theo đúng thứ tự DOM (cũ → mới)

    for row in rows:
        # ── Lấy sender ──
        sender_el = await row.query_selector('h5')
        sender = (await sender_el.inner_text()).strip() if sender_el else ""

        # ── Lấy nội dung tin nhắn ──
        text_els = await row.query_selector_all('div[dir="auto"]')
        texts = []
        for el in text_els:
            t = (await el.inner_text()).strip()
            if t:
                texts.append(t)
        message_text = "\n".join(texts).strip()

        # ── Lấy toàn bộ text của row để phân tích divider ──
        row_text = await row.inner_text()
        row_text = row_text.strip()

        # ── Phân loại: divider hay tin nhắn? ──
        if is_divider_row(row_text, bool(sender), bool(message_text)):
            date_str, time_str = parse_divider_text(row_text)
            if time_str:
                current_time = time_str
            if date_str:
                current_date = date_str
            continue  # divider không lưu vào danh sách

        # ── Bỏ qua row rỗng ──
        if not message_text:
            continue

        # ── Xây timestamp đầy đủ ──
        if current_date:
            timestamp = f"{current_date} {current_time}"
        else:
            timestamp = current_time

        # ── Dedup ──
        key = f"{sender}|{message_text}|{timestamp}"
        if key in seen_keys:
            continue

        seen_keys.add(key)
        new_msgs.append({
            "sender": sender if sender else "Không rõ người gửi",
            "message": message_text,
            "timestamp": timestamp,
        })

    # ────────────────────────────────────────────────────────────────
    # PREPEND: mỗi lần scroll lên ta thu thập tin nhắn CŨ HƠN.
    # new_msgs đang theo thứ tự DOM (cũ trước → mới sau).
    # Chèn toàn bộ vào ĐẦU chat_data để duy trì thứ tự đúng.
    # ────────────────────────────────────────────────────────────────
    chat_data[0:0] = new_msgs   # in-place prepend

    return len(new_msgs)


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

async def main():
    user_data_dir = "./facebook_profile"

    async with Stealth().use_async(async_playwright()) as p:

        print("Đang khởi chạy trình duyệt...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 720},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        wd = await page.evaluate("navigator.webdriver")
        print(f"navigator.webdriver = {wd}")

        await page.goto("https://www.facebook.com/messages/e2ee/t/849603334553929")

        print("─" * 50)
        print("Nếu lần đầu chạy → đăng nhập thủ công trong cửa sổ trình duyệt.")
        print("Phiên sẽ được lưu vào thư mục 'facebook_profile'.")
        print("─" * 50)

        input("\n[ENTER] khi đoạn chat đã hiển thị đầy đủ để bắt đầu thu thập...\n")

        chat_data: list = []
        seen_keys: set = set()

        try:
            # ── Pass 0: thu thập tin nhắn đang hiển thị (mới nhất) ──
            added = await collect_messages(page, chat_data, seen_keys)
            print(f"Pass 0 (màn hình hiện tại): +{added} tin. Tổng: {len(chat_data)}")

            # ── Hỏi số lần cuộn ──
            try:
                scroll_count = int(input("\nCuộn lên bao nhiêu lần? (0 = bỏ qua): "))
            except ValueError:
                scroll_count = 0
                print("Không hợp lệ → bỏ qua cuộn.")

            # ── Cuộn + thu thập sau mỗi lần ──
            for i in range(scroll_count):
                await page.mouse.move(500, 400)
                await page.mouse.wheel(0, -5000)
                await asyncio.sleep(2)   # chờ Facebook load nội dung cũ hơn

                added = await collect_messages(page, chat_data, seen_keys)
                print(f"Pass {i+1}/{scroll_count}: +{added} tin mới. Tổng tích lũy: {len(chat_data)}")

            # ── Lưu file ──
            if chat_data:
                out_file = "facebook_messages.json"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(chat_data, f, ensure_ascii=False, indent=4)
                print(f"\n✅ Đã lưu {len(chat_data)} tin nhắn → '{out_file}'")
            else:
                print("\n⚠️  Không tìm thấy tin nhắn. Kiểm tra selector hoặc trang chưa load xong.")

        except Exception as e:
            import traceback
            print(f"\n❌ Lỗi: {e}")
            traceback.print_exc()
        finally:
            print("\nĐóng trình duyệt...")
            await context.close()


asyncio.run(main())