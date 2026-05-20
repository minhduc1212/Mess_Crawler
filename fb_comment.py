#use for first time to set up cookie and profile for playwright
import os
import asyncio
import io
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import json
import sys

# Configure UTF-8 encoding for standard outputs
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


async def scrape_facebook_comments(page):
    print("Đang tìm kiếm bình luận...")
    try:
        await page.wait_for_selector('a[href*="comment_id"]', timeout=10000)
    except Exception:
        print("Không tìm thấy bình luận nào, hoặc trang chưa tải xong.")
        return
    #autoscroll
    print("\n--- Bắt đầu scroll ---")
    last_comment_count = 0
    stuck_counter = 0
    max_stuck = 3 # Nếu 3 lần cuộn mà không có thêm comment mới thì dừng

    # Định nghĩa chính xác Locator của bình luận để đếm
    comment_locator = page.locator('a[href*="comment_id"]').filter(has=page.locator('span[dir="auto"]'))

    while True:
        # Nhấn phím End để nhảy xuống cuối trang
        await page.keyboard.press("End")
        
        # Tạm dừng 2.5 giây để Facebook call API và render giao diện
        await page.wait_for_timeout(5000)
        
        # Đếm số lượng bình luận hiện có trên màn hình
        current_count = await comment_locator.count()
        
        if current_count > last_comment_count:
            print(f"Đang cuộn... Đã tải được {current_count} bình luận.")
            last_comment_count = current_count
            stuck_counter = 0 # Reset lại bộ đếm vì vừa load thành công
        else:
            # Nếu số lượng không đổi, cộng dồn bộ đếm
            stuck_counter += 1
            print(f"Chưa thấy bình luận mới (Thử lại {stuck_counter}/{max_stuck})...")
            
            if stuck_counter >= max_stuck:
                print("Đã cuộn đến đáy trang hoặc tải hết bình luận hiện có!\n")
                break

    # Dùng filter để lấy thẻ <a> nào bên trong có chứa thẻ span[dir="auto"]
    comment_links = await page.locator('a[href*="comment_id"]').filter(has=page.locator('span[dir="auto"]')).all()
    
    print(f"Tìm thấy {len(comment_links)} thẻ link bình luận tiềm năng.")

    results = []

    for index, link_element in enumerate(comment_links):
        try:
            # Progress logging
            if (index + 1) % 10 == 0 or index == 0 or index == len(comment_links) - 1:
                print(f"Đang xử lý bình luận {index + 1}/{len(comment_links)}...")

            raw_link = await link_element.get_attribute('href', timeout=1000)
            if not raw_link:
                continue 
                
            profile_link = raw_link.split('?')[0]

            name = await link_element.text_content(timeout=1000)
            name = name.strip() if name else ""
            
            # LỚP PHÒNG THỦ THỨ 2: Lọc bằng Python
            # Nếu tên trống hoặc vô tình lọt vào các chữ chỉ thời gian, bỏ qua ngay
            time_keywords = ["vừa xong", "phút", "giờ", "ngày", "tuần", "tháng", "năm"]
            if not name or any(keyword in name.lower() for keyword in time_keywords):
                continue

            # KHOANH VÙNG CÁI HỘP BÌNH LUẬN
            block = link_element.locator('xpath=./../../../..')
            
            # LẤY NỘI DUNG
            content_loc = block.locator('div[dir="auto"][style*="text-align"]').first
            
            if await content_loc.count() > 0:
                comment_text = await content_loc.text_content(timeout=1000)
                comment_text = comment_text.strip() if comment_text else ""
            else:
                comment_text = "[Chỉ có ảnh/Sticker hoặc không tìm thấy]"

            # LẤY THỜI GIAN CHI TIẾT
            detailed_time = ""
            try:
                article_container = link_element.locator('xpath=ancestor::div[@role="article"]').first
                all_links = article_container.locator('a[href*="comment_id"]')
                link_count = await all_links.count()
                
                timestamp_el = None
                relative_time = ""
                
                for idx in range(link_count):
                    el = all_links.nth(idx)
                    el_text = await el.text_content(timeout=1000)
                    el_text = el_text.strip() if el_text else ""
                    
                    # Process of elimination: timestamp link is non-empty and is not the author's name link
                    if el_text and el_text != name:
                        timestamp_el = el
                        relative_time = el_text
                        break
                
                if timestamp_el:
                    detailed_time = relative_time  # Fallback to relative time
                    
                    try:
                        # Clear any existing tooltip by moving mouse away
                        await page.mouse.move(0, 0)
                        try:
                            # Wait briefly for previous tooltip to be hidden
                            await page.wait_for_selector('div[role="tooltip"]', state="hidden", timeout=300)
                        except Exception:
                            pass
                            
                        # Hover over the timestamp element to trigger the tooltip
                        await timestamp_el.scroll_into_view_if_needed(timeout=2000)
                        await asyncio.sleep(0.3)  # Let UI settle after scroll
                        await timestamp_el.hover(timeout=3000)
                        
                        # Wait for the tooltip to become visible (up to 3s)
                        try:
                            await page.wait_for_selector('div[role="tooltip"]', state="visible", timeout=3000)
                            tooltip = page.locator('div[role="tooltip"]')
                            if await tooltip.count() > 0:
                                tooltip_text = await tooltip.first.text_content(timeout=500)
                                if tooltip_text:
                                    detailed_time = tooltip_text.strip()
                                    # Optimization: Proceed immediately after success
                                    await page.mouse.move(0, 0)
                                    # No extra sleep needed here
                        except Exception:
                            # Tooltip failed to appear in 3s, keep relative time fallback
                            pass
                    except Exception:
                        # Fallback silently and keep the relative time
                        pass
            except Exception as e:
                # We don't want to spam errors for every comment if extraction fails
                pass

            # Thêm vào kết quả
            results.append({
                "user": name,
                "link": profile_link,
                "time": detailed_time,
                "content": comment_text
            })

        except Exception:
            continue
    
    #save to json
    with open('comments.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    # In kết quả
    print(f"\n--- ĐÃ LỌC ĐƯỢC {len(results)} BÌNH LUẬN HỢP LỆ ---")
    for r in results:
        print(f"Tên: {r['user']}")
        print(f"Link: {r['link']}")
        print(f"Thời gian: {r['time']}")
        print(f"Nội dung: {r['content']}")
        print("-" * 40)


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

        await page.goto("https://www.facebook.com/UrbanHermitOG/posts/pfbid033fBsWQ28zeAJjACcnuE1CawLFsKYwPG8DPqSk3VCRbXTGTN5h9tTbJoinf75jBzbl")
        print("─" * 55)
        print("Nếu lần đầu → đăng nhập thủ công rồi nhấn Enter.")
        print("─" * 55)
        input("\n[ENTER] khi đã đăng nhập...\n")

        #enter the buton "phù hợp nhất" ở xpath /html/body/div[1]/div/div[1]/div/div[5]/div/div/div[2]/div/div/div/div/div/div/div/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div/div/div/div/div/div[13]/div/div/div[4]/div/div/div[2]/div[1]/div/div/span hoặc cách dưới đây
        print("\nNhấn vào nút 'Phù hợp nhất' để hiển thị bình luận theo thứ tự mới nhất...")
        # Sử dụng async/await trong Playwright
        await page.get_by_role("button", name="Phù hợp nhất").click()
        #sleep 10s
        print ("Đã nhấn nút 'Phù hợp nhất'")
        await asyncio.sleep(5)
        
        #ấn vào nút "Tất cả bình luận" 
        #full xpath của nút "Tất cả bình luận": xpath=/html/body/div[1]/div/div[1]/div/div[5]/div/div/div[3]/div/div/div[1]/div[1]/div/div/div/div/div/div/div[1]/div/div[3]/div[1]/div/div[1]/span
        print("\nNhấn vào nút 'Tất cả bình luận' để hiển thị tất cả bình luận...")
        await page.get_by_text("Tất cả bình luận", exact=True).first.click()
        print ("Đã nhấn nút 'Tất cả bình luận'")
        await asyncio.sleep(10)

        #lấy comment
        print("\nĐang lấy bình luận...")
        await scrape_facebook_comments(page)
        await asyncio.sleep(5)

        print("\nĐóng trình duyệt...")
        await context.close()

asyncio.run(main())