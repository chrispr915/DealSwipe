"""
Selenium ASIN fetcher v2 — restarts browser on crash, processes remaining products.
"""

import re
import time
import random
import os
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions

AFFILIATE_TAG = "dealswipes-20"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# Only products that still need real ASINs (cosmetics + fitness)
PRODUCTS = [
    "Dyson Airwrap Multi-Styler Complete",
    "Charlotte Tilbury Hollywood Flawless Filter",
    "Tatcha Dewy Skin Cream Moisturizer",
    "COSRX Snail Mucin 96% Power Repairing Essence",
    "Laneige Lip Sleeping Mask Berry",
    "Drunk Elephant Protini Polypeptide Cream",
    "Olaplex No.3 Hair Perfector Treatment",
    "NuFace Mini+ Starter Kit Toning Device",
    "Apple Watch SE 2nd Gen 40mm GPS",
    "Bowflex SelectTech 552 Adjustable Dumbbells",
    "Theragun Relief Handheld Massage Gun",
    "Hydro Flask 32oz Wide Mouth Bottle",
    "Garmin Venu Sq 2 GPS Smartwatch",
    "Optimum Nutrition Gold Standard Whey 5lb",
    "Manduka PRO Yoga Mat 71",
    "Fit Simplify Resistance Loop Bands Set",
]


def new_driver():
    opts = EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    return webdriver.Edge(options=opts)


def search_asin(driver, product_name):
    url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
    driver.get(url)
    time.sleep(random.uniform(3, 5))
    source = driver.page_source
    asins = re.findall(r'data-asin="([A-Z0-9]{10})"', source)
    asins = [a for a in asins if a.strip()]
    if asins:
        return asins[0]
    asins = re.findall(r'/dp/([A-Z0-9]{10})', source)
    return asins[0] if asins else None


def update_html(asin_map):
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    updated = 0
    for product_name, asin in asin_map.items():
        new_url = f"https://www.amazon.com/dp/{asin}?tag="
        escaped_title = re.escape(product_name)
        block_pattern = re.compile(
            r"(title:\s*'" + escaped_title.replace(r"\ ", r"[\s\-]") + r"'.*?url:\s*')(https://www\.amazon\.com/[^']+?)(' \+ AFFILIATE_TAG)",
            re.DOTALL
        )
        match = block_pattern.search(html)
        if match:
            html = html[:match.start(2)] + new_url + html[match.end(2):]
            updated += 1

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return updated


def main():
    print("=" * 55)
    print("  ASIN Fetcher — Cosmetics & Fitness")
    print("=" * 55)

    driver = None
    asin_map = {}
    total = len(PRODUCTS)

    for i, product in enumerate(PRODUCTS, 1):
        print(f"\n[{i}/{total}] {product}")

        # Create or restart driver
        if driver is None:
            try:
                driver = new_driver()
                print("    (browser started)")
            except Exception as e:
                print(f"    Can't start browser: {e}")
                continue

        try:
            asin = search_asin(driver, product)
            if asin:
                print(f"    ASIN: {asin} -> amazon.com/dp/{asin}")
                asin_map[product] = asin
            else:
                print("    No ASIN found")
        except Exception as e:
            print(f"    Error (restarting browser): {type(e).__name__}")
            try:
                driver.quit()
            except:
                pass
            driver = None
            # Retry with fresh browser
            try:
                driver = new_driver()
                time.sleep(2)
                asin = search_asin(driver, product)
                if asin:
                    print(f"    ASIN (retry): {asin} -> amazon.com/dp/{asin}")
                    asin_map[product] = asin
                else:
                    print("    No ASIN found on retry")
            except Exception as e2:
                print(f"    Retry also failed: {type(e2).__name__}")
                try:
                    driver.quit()
                except:
                    pass
                driver = None

        if i < total:
            time.sleep(random.uniform(2, 4))

    if driver:
        try:
            driver.quit()
        except:
            pass

    print(f"\n{'=' * 55}")
    print(f"  Found {len(asin_map)}/{total} ASINs")

    if asin_map:
        print("  Updating index.html...")
        updated = update_html(asin_map)
        print(f"  Updated {updated} links")
        print("\n  Results:")
        for name, asin in asin_map.items():
            print(f"    {asin} — {name[:50]}")

    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
