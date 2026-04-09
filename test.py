import asyncio
from playwright.async_api import async_playwright

# ====================================================================
# ĐIỀN THÔNG TIN TEST VÀO ĐÂY
# ====================================================================
TARGET_XPATH = "/html/body/div[1]/div/div[1]/div/div[5]/div/div/div[2]/div/div/div/div/div/div/div/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div/div/div/div/div/div[13]/div/div/div[3]/div[2]/div[1]/div/div/div/div[1]/a/div[1]/div[1]/div/img"

# Thay link bài viết chứa cái ảnh đó vào đây
TEST_URL = "https://www.facebook.com/groups/361726451351144/permalink/2228645754659195/" 

async def test_click_xpath():
    # Trỏ đúng vào thư mục profile đang chứa cookie đăng nhập của bạn
    user_data_dir = "./facebook_profile"

    async with async_playwright() as p:
        print("[*] Đang khởi động trình duyệt...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True, # Mở giao diện lên để quan sát
            viewport={"width": 1280, "height": 720},
            args=["--lang=vi-VN,vi"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"[*] Đang mở link: {TEST_URL}")
        # Mở trang và chờ DOM tải xong
        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=30_000)
        
        print("[*] Đang chờ 5 giây để Facebook render xong mọi thứ...")
        await asyncio.sleep(5) 

        print(f"[*] Đang tìm kiếm XPath...")
        try:
            # Playwright hỗ trợ prefix 'xpath='
            locator = page.locator(f"xpath={TARGET_XPATH}").first
            
            # Chờ tối đa 5 giây để phần tử xuất hiện trên màn hình
            await locator.wait_for(state="visible", timeout=5000)
            
            # --- CHIÊU TRÒ DEBUG: Vẽ khung đỏ quanh phần tử tìm được ---
            print("[-] Đã tìm thấy! Đang vẽ khung đỏ để đánh dấu...")
            await locator.evaluate("el => el.style.border = '5px solid red'")
            await asyncio.sleep(2) # Dừng 2 giây để bạn kịp nhìn bằng mắt thật
            # -----------------------------------------------------------

            print("[-] Đang thực hiện CLICK!")
            await locator.click()
            
            print("\n" + "═"*60)
            print("✅ BẮT TRÚNG ĐÍCH VÀ CLICK THÀNH CÔNG!")
            print("═"*60 + "\n")

        except Exception as e:
            print("\n" + "═"*60)
            print("❌ TRƯỢT MỤC TIÊU! Không thể click vào phần tử ở XPath này.")
            print(f"Lỗi chi tiết: {e}")
            print("═"*60 + "\n")

        print("[*] Đợi 10 giây để bạn quan sát kết quả sau khi click rồi đóng...")
        await asyncio.sleep(10)
        await context.close()

if __name__ == "__main__":
    asyncio.run(test_click_xpath())