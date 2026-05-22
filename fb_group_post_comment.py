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
        # Chờ bất kỳ element nào có vẻ là nội dung bình luận
        await page.wait_for_selector('div[dir="auto"][style*="text-align"]', timeout=10000)
    except Exception:
        print("Không tìm thấy bình luận nào, hoặc trang chưa tải xong.")
        return []

    print("\n--- Bắt đầu scroll ---")
    count_locator = page.locator('div[dir="auto"][style*="text-align"]')
    last_comment_count = 0
    stuck_counter = 0
    max_stuck = 3

    while True:
        await page.keyboard.press("End")
        await page.wait_for_timeout(4000)
        current_count = await count_locator.count()
        if current_count > last_comment_count:
            print(f"Đang cuộn... Đã tải được khoảng {current_count} khối text bình luận.")
            last_comment_count = current_count
            stuck_counter = 0
        else:
            stuck_counter += 1
            if stuck_counter >= max_stuck:
                print("Đã cuộn đến đáy trang hoặc tải hết bình luận hiện có!\n")
                break

    print(f"Đã xác định có khối text bình luận, bắt đầu phân tích cấu trúc...")

    results = []
    seen_keys = {}

    # Phương pháp 1: Lấy qua role="article" (cách chuẩn của Facebook)
    articles = await page.locator('div[role="article"]').all()
    
    for index, article in enumerate(articles):
        try:
            author_loc = article.locator('a[role="link"]').filter(has=page.locator('span[dir="auto"]'))
            if await author_loc.count() == 0:
                continue
            
            author_link_el = author_loc.first
            raw_link = await author_link_el.get_attribute('href', timeout=1000)
            if not raw_link: continue
            
            name = await author_link_el.text_content(timeout=1000)
            name = name.strip() if name else ""
            time_keywords = ["vừa xong", "phút", "giờ", "ngày", "tuần", "tháng", "năm"]
            if not name or any(keyword in name.lower() for keyword in time_keywords):
                continue
                
            profile_link = raw_link.split('?')[0]
            
            text_locs = await article.locator('div[dir="auto"][style*="text-align"]').all()
            texts = []
            for t in text_locs:
                txt = await t.text_content(timeout=1000)
                if txt: texts.append(txt.strip())
            
            comment_text = "\n".join(texts) if texts else "[Chỉ có ảnh/Sticker hoặc không tìm thấy]"
            
            detailed_time = ""
            all_links = await article.locator('a[role="link"]').all()
            timestamp_el = None
            relative_time = ""
            for el in all_links:
                el_text = await el.text_content(timeout=1000)
                el_text = el_text.strip() if el_text else ""
                if el_text and el_text != name and any(k in el_text.lower() for k in time_keywords + ["lúc"]):
                    timestamp_el = el
                    relative_time = el_text
                    break
            
            if timestamp_el:
                detailed_time = relative_time
                try:
                    await timestamp_el.hover(timeout=2000)
                    tooltip = page.locator('div[role="tooltip"]')
                    if await tooltip.count() > 0:
                        tt_text = await tooltip.first.text_content(timeout=1000)
                        if tt_text: detailed_time = tt_text.strip()
                except Exception: pass
            
            dedup_key = (name, profile_link, comment_text)
            if dedup_key in seen_keys:
                existing_idx = seen_keys[dedup_key]
                if 'lúc' not in results[existing_idx]['time'] and 'lúc' in detailed_time: 
                    results[existing_idx]['time'] = detailed_time
                continue
            
            seen_keys[dedup_key] = len(results)
            results.append({"user": name, "link": profile_link, "time": detailed_time, "content": comment_text})
            
        except Exception:
            continue
            
    # Phương pháp 2: Nếu role="article" không tìm được (Facebook Group có thể ẩn role), fallback về cấu trúc Bubble
    if len(results) <= 1:
        print("[-] Không tìm thấy comment qua role='article', thử dùng cấu trúc Bubble chung...")
        author_links = await page.locator('a[role="link"]').filter(has=page.locator('span[dir="auto"]')).all()
        for index, link_element in enumerate(author_links):
            try:
                raw_link = await link_element.get_attribute('href', timeout=1000)
                if not raw_link: continue
                name = await link_element.text_content(timeout=1000)
                name = name.strip() if name else ""
                if not name or any(keyword in name.lower() for keyword in time_keywords): continue
                
                profile_link = raw_link.split('?')[0]
                
                # Bubble là khối div chứa cả tên tác giả và text.
                # Tìm thẻ div gần nhất bọc ngoài tên tác giả (ancestor thứ nhất)
                bubble = link_element.locator('xpath=ancestor::div[1]')
                if await bubble.count() == 0: continue
                
                text_locs = await bubble.locator('div[dir="auto"][style*="text-align"]').all()
                texts = []
                for t in text_locs:
                    txt = await t.text_content(timeout=1000)
                    if txt: texts.append(txt.strip())
                
                comment_text = "\n".join(texts) if texts else "[Chỉ có ảnh/Sticker hoặc không tìm thấy]"
                
                detailed_time = ""
                outer_container = link_element.locator('xpath=ancestor::div[3]')
                if await outer_container.count() > 0:
                    time_links = await outer_container.locator('a[role="link"]').all()
                    for el in time_links:
                        el_text = await el.text_content(timeout=1000)
                        el_text = el_text.strip() if el_text else ""
                        if el_text and el_text != name and any(k in el_text.lower() for k in time_keywords):
                            detailed_time = el_text
                            break
                            
                dedup_key = (name, profile_link, comment_text)
                if dedup_key in seen_keys: continue
                
                seen_keys[dedup_key] = len(results)
                results.append({"user": name, "link": profile_link, "time": detailed_time, "content": comment_text})
            except Exception:
                continue

    # Lưu lại kết quả
    with open('comments.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"\n--- ĐÃ LỌC ĐƯỢC {len(results)} BÌNH LUẬN HỢP LỆ ---")
    for r in results:
        print(f"Tên: {r['user']}")
        print(f"Link: {r['link']}")
        print(f"Thời gian: {r['time']}")
        print(f"Nội dung: {r['content']}")
        print("-" * 40)

    return results


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

        await page.goto("https://www.facebook.com/groups/sportsbook6vn/permalink/1345769944078750/")
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