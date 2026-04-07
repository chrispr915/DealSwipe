"""
Scrapes REAL discounted products from Amazon for each category.
Gets: title, ASIN, price, original price, discount %, image URL.
Then updates index.html with actual live deals.
"""

import re
import json
import time
import random
import os
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

AFFILIATE_TAG = "dealswipes-20"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# Amazon search queries for each category — filtered for deals
CATEGORIES = {
    "gaming": [
        "gaming headset deal",
        "gaming mouse deal",
        "gaming keyboard deal",
        "gaming monitor deal",
        "gaming controller deal",
        "gaming SSD deal",
        "gaming chair deal",
        "gaming mousepad deal",
    ],
    "cosmetics": [
        "skincare deal",
        "makeup deal",
        "hair care deal",
        "lip mask deal",
        "moisturizer deal",
        "face serum deal",
        "beauty tools deal",
        "perfume deal",
    ],
    "fitness": [
        "fitness tracker deal",
        "dumbbells deal",
        "massage gun deal",
        "water bottle deal",
        "protein powder deal",
        "yoga mat deal",
        "resistance bands deal",
        "jump rope fitness deal",
    ],
}


def new_driver():
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Edge(options=opts)


def scrape_deal(driver, search_query):
    """Search Amazon and find first product with a visible discount."""
    url = f"https://www.amazon.com/s?k={search_query.replace(' ', '+')}&deals-widget=%257B%2522version%2522%253A1%252C%2522viewIndex%2522%253A0%252C%2522presetId%2522%253A%2522deals-collection-all-702702%2522%252C%2522dealType%2522%253A%2522DEAL%2522%252C%2522sorting%2522%253A%2522BY_DISCOUNT_DESCENDING%2522%257D"
    driver.get(url)
    time.sleep(random.uniform(3, 5))

    source = driver.page_source
    product = None

    # Try to find products with discount info from search results
    try:
        results = driver.find_elements(By.CSS_SELECTOR, '[data-component-type="s-search-result"]')

        for result in results[:10]:
            try:
                data_asin = result.get_attribute("data-asin")
                if not data_asin or len(data_asin) != 10:
                    continue

                result_html = result.get_attribute("innerHTML")

                # Get title
                title_el = result.find_elements(By.CSS_SELECTOR, "h2 span")
                if not title_el:
                    continue
                title = title_el[0].text.strip()
                if not title or len(title) < 10:
                    continue

                # Get image
                img_el = result.find_elements(By.CSS_SELECTOR, "img.s-image")
                img_url = img_el[0].get_attribute("src") if img_el else ""

                # Get prices — look for both current and original price
                price_whole = result.find_elements(By.CSS_SELECTOR, "span.a-price-whole")
                price_frac = result.find_elements(By.CSS_SELECTOR, "span.a-price-fraction")

                if not price_whole:
                    continue

                current_price = float(price_whole[0].text.replace(",", "").replace(".", ""))
                if price_frac:
                    frac = price_frac[0].text.strip()
                    current_price += float(f"0.{frac}")

                # Look for original price (struck-through)
                original_price = 0
                old_prices = result.find_elements(By.CSS_SELECTOR, "span.a-price.a-text-price span.a-offscreen")
                if old_prices:
                    price_text = old_prices[0].get_attribute("textContent").replace("$", "").replace(",", "").strip()
                    try:
                        original_price = float(price_text)
                    except:
                        pass

                # Also check for discount percentage text
                discount_pct = 0
                discount_spans = result.find_elements(By.XPATH, ".//*[contains(text(), '% off')]")
                if discount_spans:
                    pct_match = re.search(r'(\d+)%', discount_spans[0].text)
                    if pct_match:
                        discount_pct = int(pct_match.group(1))

                # Calculate discount
                if original_price > current_price:
                    discount_pct = round((1 - current_price / original_price) * 100)
                elif discount_pct > 0 and original_price == 0:
                    original_price = round(current_price / (1 - discount_pct / 100), 2)

                # Only include if there's a real discount
                if discount_pct >= 10 and original_price > current_price:
                    product = {
                        "title": title[:80],
                        "asin": data_asin,
                        "price": current_price,
                        "was": original_price,
                        "discount": discount_pct,
                        "img": img_url,
                    }
                    break

            except Exception as e:
                continue

    except Exception as e:
        print(f"    Parse error: {e}")

    return product


def build_js_product(p):
    """Format a product as a JS object string."""
    return (
        f"    {{\n"
        f"      title: '{p['title'].replace(chr(39), chr(92)+chr(39))}',\n"
        f"      img: '{p['img']}',\n"
        f"      price: {p['price']:.2f}, was: {p['was']:.2f}, discount: {p['discount']}, store: 'Amazon',\n"
        f"      url: 'https://www.amazon.com/dp/{p['asin']}?tag=' + AFFILIATE_TAG\n"
        f"    }}"
    )


def update_html(categories_data):
    """Rewrite the products object in index.html."""
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Build new products JS block
    sections = []
    for cat, products in categories_data.items():
        items = ",\n".join(build_js_product(p) for p in products)
        sections.append(f"  {cat}: [\n{items}\n  ]")

    new_products = "const products = {\n" + ",\n".join(sections) + "\n};"

    # Replace old products block
    pattern = re.compile(r'const products = \{.*?\};', re.DOTALL)
    html = pattern.sub(new_products, html)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    print("=" * 58)
    print("  SwipeDeals — Live Deal Scraper")
    print("  Fetching REAL discounted products from Amazon...")
    print("=" * 58)

    driver = None
    categories_data = {}

    for cat, queries in CATEGORIES.items():
        print(f"\n{'-' * 40}")
        print(f"  Category: {cat.upper()}")
        print(f"{'-' * 40}")

        products = []

        for j, query in enumerate(queries):
            print(f"\n  [{j+1}/{len(queries)}] Searching: {query}")

            # Start/restart browser as needed
            if driver is None:
                try:
                    driver = new_driver()
                except Exception as e:
                    print(f"    Browser error: {e}")
                    continue

            try:
                product = scrape_deal(driver, query)
                if product:
                    # Check we don't already have this ASIN
                    if not any(p["asin"] == product["asin"] for p in products):
                        products.append(product)
                        print(f"    FOUND: {product['title'][:55]}...")
                        print(f"    ${product['price']:.2f} (was ${product['was']:.2f}) -{product['discount']}%")
                        print(f"    ASIN: {product['asin']}")
                    else:
                        print(f"    Duplicate ASIN, skipping")
                else:
                    print(f"    No discounted product found")
            except Exception as e:
                print(f"    Error: {type(e).__name__} — restarting browser")
                try:
                    driver.quit()
                except:
                    pass
                driver = None
                time.sleep(2)

            time.sleep(random.uniform(2, 4))

        if products:
            categories_data[cat] = products
            print(f"\n  Got {len(products)} deals for {cat}")
        else:
            print(f"\n  No deals found for {cat}")

    if driver:
        try:
            driver.quit()
        except:
            pass

    # Update HTML
    print(f"\n{'=' * 58}")
    total = sum(len(v) for v in categories_data.values())
    print(f"  Total deals found: {total}")

    if categories_data:
        print("  Updating index.html...")
        update_html(categories_data)
        print("  Done! Refresh index.html to see live deals.")
    else:
        print("  No deals found. Amazon may be blocking requests.")

    print(f"{'=' * 58}")


if __name__ == "__main__":
    main()
