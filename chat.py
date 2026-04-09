import asyncio
import os
import io
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

try:
    from PIL import Image, ImageChops
except ImportError:
    print("Lỗi: Thư viện Pillow chưa được cài đặt. Vui lòng chạy: pip install Pillow")
    exit()

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

async def main():
    user_data_dir = "./facebook_profile"
    output_dir = "chat_screenshots"  # Thư mục lưu ảnh chụp màn hình

    # Tạo thư mục nếu chưa có
    os.makedirs(output_dir, exist_ok=True)

    async with Stealth().use_async(async_playwright()) as p:

        print("Đang khởi chạy trình duyệt...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 720},
        )

        page = context.pages[0] if context.pages else await context.new_page()
        print(f"navigator.webdriver = {await page.evaluate('navigator.webdriver')}")

        await page.goto("https://www.facebook.com/messages/e2ee/t/849603334553929")
        print("─" * 55)
        print("Nếu lần đầu → đăng nhập thủ công rồi nhấn Enter.")
        print("─" * 55)
        input("\n[ENTER] khi chat đã hiển thị đầy đủ...\n")

        try:
            print("\nBắt đầu chụp ảnh và cuộn lên cho đến khi hết...")
            i = 0
            
            # Chụp và lưu ảnh màn hình ban đầu
            initial_path = os.path.join(output_dir, f"screenshot_{i}.png")
            previous_screenshot_bytes = await page.screenshot(path=initial_path)
            print(f"Đã lưu: {initial_path}")

            while True:
                # Cuộn lên
                await page.mouse.move(500, 400)
                await page.mouse.wheel(0, -450)
                await asyncio.sleep(2)  # Chờ nội dung mới tải

                # Chụp ảnh màn hình mới
                current_screenshot_bytes = await page.screenshot()

                # So sánh với ảnh trước đó
                img1 = Image.open(io.BytesIO(previous_screenshot_bytes))
                img2 = Image.open(io.BytesIO(current_screenshot_bytes))
                diff = ImageChops.difference(img1, img2)

                # Nếu không có sự khác biệt, tức là đã cuộn đến đầu
                if diff.getbbox() is None:
                    print("\nĐã cuộn đến đầu cuộc trò chuyện. Dừng lại.")
                    break
                
                # Nếu khác, lưu ảnh mới và tiếp tục
                i += 1
                path = os.path.join(output_dir, f"screenshot_{i}.png")
                with open(path, "wb") as f:
                    f.write(current_screenshot_bytes)
                print(f"Đã lưu: {path}")

                # Cập nhật ảnh trước đó cho vòng lặp tiếp theo
                previous_screenshot_bytes = current_screenshot_bytes

            print(f"\n✅ Hoàn tất! Đã lưu {i + 1} ảnh vào thư mục '{output_dir}'.")

        except Exception as e:
            import traceback
            print(f"\n❌ Lỗi: {e}")
            traceback.print_exc()
        finally:
            print("\nĐóng trình duyệt...")
            await context.close()

asyncio.run(main())