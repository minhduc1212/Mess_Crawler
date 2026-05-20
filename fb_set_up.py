#use for first time to set up cookie and profile for playwright
import os
import asyncio
import os
import io
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

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
        print(f"navigator.webdriver = {await page.evaluate('navigator.webdriver')}")

        await page.goto("https://www.facebook.com")
        print("─" * 55)
        print("Nếu lần đầu → đăng nhập thủ công rồi nhấn Enter.")
        print("─" * 55)
        input("\n[ENTER] khi đã đăng nhập...\n")

        print("\nĐóng trình duyệt...")
        await context.close()

asyncio.run(main())