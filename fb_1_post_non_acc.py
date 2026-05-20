from playwright.sync_api import sync_playwright

def crawl_fb_posts(url):
    with sync_playwright() as p:
        # Mở trình duyệt có giao diện (headless=False) để dễ debug và tránh bị FB chặn sớm
        browser = p.chromium.launch(headless=False) 
        page = browser.new_page()
        page.goto(url)

        # Chờ cho đến khi ít nhất một bài viết (container) xuất hiện
        page.wait_for_selector('div[role="article"]', timeout=15000)

        # Lấy tất cả các container của bài viết hiện có trên màn hình
        post_containers = page.locator('div[role="article"]').all()

        for index, post in enumerate(post_containers):
            try:
                text_elements = post.locator('div[dir="auto"]').all()
                
                caption = ""
                if text_elements:
                    # Lấy text của phần tử dir="auto" đầu tiên
                    caption = text_elements[0].inner_text()
                
                print(f"--- Bài viết {index + 1} ---")
                print(f"Caption: {caption}\n")
                
            except Exception as e:
                print(f"Lỗi khi lấy dữ liệu bài viết {index + 1}: {e}")

        browser.close()

if __name__ == '__main__':
    # Thay bằng link group hoặc fanpage bạn muốn cào
    crawl_fb_posts('https://www.facebook.com/share/p/1AXVrtgXjv/')