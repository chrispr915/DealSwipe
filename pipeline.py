"""
SwipeDeals Data Pipeline
========================
1. INGEST  - Scrape deals from Amazon via Selenium
2. PROCESS - Clean data, validate, filter 50%+ discount
3. STORE   - Upsert into SQLite database
4. UPDATE  - Expire old deals, delete stale, regenerate index.html

Usage:
    python pipeline.py              # Full pipeline
    python pipeline.py --refresh    # Just regenerate HTML from DB
    python pipeline.py --stats      # Show database stats
"""

import re
import sys
import time
import random
import os
from datetime import datetime

import db

AFFILIATE_TAG = "dealswipes-20"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
MIN_DISCOUNT = 40

# Search queries per category — diverse terms to find good deals
SEARCH_QUERIES = {
    "gaming": [
        "gaming headset deal",
        "gaming mouse discount",
        "gaming keyboard sale",
        "gaming monitor deal",
        "gaming controller discount",
        "SSD NVMe deal",
        "gaming chair sale",
        "gaming mousepad deal",
        "webcam streaming deal",
        "gaming microphone sale",
        "RGB gaming speakers",
        "gaming desk deal",
    ],
    "cosmetics": [
        "makeup deal",
        "skincare sale",
        "mascara deal",
        "face serum discount",
        "lip gloss sale",
        "eye cream deal",
        "foundation makeup deal",
        "hair treatment oil",
        "beauty tools deal",
        "nail polish set deal",
        "face moisturizer deal",
        "perfume women deal",
    ],
    "fitness": [
        "dumbbells deal",
        "fitness tracker discount",
        "yoga mat sale",
        "resistance bands deal",
        "protein powder deal",
        "water bottle insulated deal",
        "massage gun deal",
        "jump rope fitness",
        "pull up bar deal",
        "workout gloves deal",
        "foam roller deal",
        "kettlebell deal",
    ],
    "tech": [
        "wireless earbuds deal",
        "bluetooth speaker deal",
        "laptop stand deal",
        "USB C hub deal",
        "portable charger deal",
        "smart plug deal",
        "LED desk lamp deal",
        "phone case deal",
        "tablet stand deal",
        "webcam HD deal",
        "keyboard wireless deal",
        "mouse wireless deal",
    ],
    "home": [
        "kitchen gadgets deal",
        "air purifier deal",
        "LED light strip deal",
        "bedding sheets deal",
        "vacuum cleaner deal",
        "coffee maker deal",
        "candle set deal",
        "storage organizer deal",
        "blender deal",
        "towel set deal",
        "throw blanket deal",
        "wall art decor deal",
    ],
    "outdoors": [
        "camping gear deal",
        "hiking backpack deal",
        "portable hammock deal",
        "water filter bottle deal",
        "solar charger deal",
        "camping lantern deal",
        "sunglasses polarized deal",
        "fishing gear deal",
        "bike accessories deal",
        "tent camping deal",
        "cooler bag deal",
        "headlamp deal",
    ],
    "kids": [
        "kids toys deal",
        "LEGO set deal",
        "kids tablet deal",
        "board game family deal",
        "kids water bottle deal",
        "children book set deal",
        "kids headphones deal",
        "arts crafts kids deal",
        "stuffed animal deal",
        "kids backpack deal",
        "puzzle kids deal",
        "outdoor toys kids deal",
    ],
}


# =========================================================
# STEP 1: INGEST — Scrape Amazon
# =========================================================
def create_driver():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Edge(options=opts)


def scrape_search(driver, query):
    """Scrape Amazon search results, return list of raw product dicts."""
    from selenium.webdriver.common.by import By

    url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    driver.get(url)
    time.sleep(random.uniform(3, 5))

    raw_products = []
    try:
        results = driver.find_elements(By.CSS_SELECTOR, '[data-component-type="s-search-result"]')
        for result in results[:15]:
            try:
                asin = result.get_attribute("data-asin")
                if not asin or len(asin) != 10:
                    continue

                title_el = result.find_elements(By.CSS_SELECTOR, "h2 span")
                if not title_el:
                    continue
                title = title_el[0].text.strip()
                if not title or len(title) < 10:
                    continue

                img_el = result.find_elements(By.CSS_SELECTOR, "img.s-image")
                img_url = img_el[0].get_attribute("src") if img_el else ""

                price_whole = result.find_elements(By.CSS_SELECTOR, "span.a-price-whole")
                price_frac = result.find_elements(By.CSS_SELECTOR, "span.a-price-fraction")
                if not price_whole:
                    continue
                current = float(price_whole[0].text.replace(",", "").replace(".", ""))
                if price_frac:
                    current += float(f"0.{price_frac[0].text.strip()}")

                original = 0

                # Get the full result HTML to check for per-unit pricing
                result_text = result.text

                # Check if this has per-unit pricing (/Fl Oz, /Ounce, /Count, etc.)
                # These show a high "price per unit" that looks like an original price
                has_per_unit = bool(re.search(
                    r'\$/?(Fl\s*Oz|Ounce|Count|oz|ml|lb|Gram|ct|Each|Item)',
                    result_text, re.IGNORECASE
                ))

                # Only look for struck-through original price if no per-unit pricing confusion
                old = result.find_elements(By.CSS_SELECTOR, "span.a-price.a-text-price span.a-offscreen")
                if old:
                    try:
                        candidate = float(old[0].get_attribute("textContent").replace("$", "").replace(",", "").strip())
                        # Sanity checks to avoid per-unit price confusion:
                        # 1. Original should be > current but not absurdly higher
                        # 2. If per-unit pricing detected, be extra strict
                        # 3. Keep ratios realistic — real deals rarely exceed 3x
                        max_ratio = 2.0 if has_per_unit else 3.0
                        if current < candidate <= current * max_ratio:
                            original = candidate
                    except:
                        pass

                raw_products.append({
                    "asin": asin,
                    "title": title,
                    "price": current,
                    "was": original,
                    "img": img_url,
                })
            except:
                continue
    except:
        pass

    return raw_products


def ingest(categories=None):
    """Scrape all categories, return raw products."""
    if categories is None:
        categories = list(SEARCH_QUERIES.keys())

    print("\n  STEP 1: INGEST (scraping Amazon)")
    print("  " + "-" * 45)

    driver = None
    all_raw = {}

    for cat in categories:
        queries = SEARCH_QUERIES.get(cat, [])
        all_raw[cat] = []
        seen_asins = set()

        print(f"\n  [{cat.upper()}]")

        for j, query in enumerate(queries):
            if driver is None:
                try:
                    driver = create_driver()
                except Exception as e:
                    print(f"    Browser error: {e}")
                    break

            print(f"    {j+1}/{len(queries)} '{query}' ", end="", flush=True)

            try:
                products = scrape_search(driver, query)
                new = 0
                for p in products:
                    if p["asin"] not in seen_asins:
                        p["category"] = cat
                        all_raw[cat].append(p)
                        seen_asins.add(p["asin"])
                        new += 1
                print(f"-> {new} new products")
            except Exception as e:
                print(f"-> ERROR ({type(e).__name__}), restarting browser")
                try:
                    driver.quit()
                except:
                    pass
                driver = None

            time.sleep(random.uniform(2, 3))

        print(f"    Total raw: {len(all_raw[cat])}")

    if driver:
        try:
            driver.quit()
        except:
            pass

    return all_raw


# =========================================================
# STEP 2: PROCESS — Clean + calculate + filter
# =========================================================
def process(raw_data, min_discount=MIN_DISCOUNT):
    """Clean data, calculate discounts, filter for min_discount%."""
    print(f"\n  STEP 2: PROCESS (clean + filter >= {min_discount}% off)")
    print("  " + "-" * 45)

    processed = {}

    for cat, products in raw_data.items():
        cleaned = []

        for p in products:
            # Skip if missing essential data
            if not p.get("asin") or not p.get("title") or not p.get("price"):
                continue

            # Clean title — remove excessive whitespace, limit length
            title = re.sub(r'\s+', ' ', p["title"]).strip()[:100]

            # Skip junk titles
            if any(word in title.lower() for word in ["sponsored", "editorial"]):
                continue

            price = round(p["price"], 2)
            was = round(p.get("was", 0), 2)

            # Skip free or suspiciously cheap items
            if price < 1.00:
                continue

            # Skip fake discounts: if "was" price is absurdly higher, it's probably
            # a per-ounce/per-unit price, not a real original price
            if was > price * 3:
                continue

            # Calculate discount
            if was > price:
                discount = round((1 - price / was) * 100)
            else:
                discount = 0

            # FILTER: only 50%+ discounts
            if discount < min_discount:
                continue

            # Build product URL
            url = f"https://www.amazon.com/dp/{p['asin']}?tag={AFFILIATE_TAG}"

            # Upgrade image to high-res (500px) — Amazon thumbnails are tiny/pixelated
            img = p.get("img", "")
            img = re.sub(r'\._AC_[A-Z]+\d+_\.', '._AC_SL500_.', img)

            cleaned.append({
                "asin": p["asin"],
                "title": title,
                "category": cat,
                "price": price,
                "was": was,
                "discount": discount,
                "img": img,
                "url": url,
                "store": "Amazon",
            })

        # Sort by discount descending
        cleaned.sort(key=lambda x: x["discount"], reverse=True)

        # Keep top 10 per category
        processed[cat] = cleaned[:10]

        print(f"    {cat}: {len(products)} raw -> {len(cleaned)} at {min_discount}%+ -> keeping top {len(processed[cat])}")

    return processed


# =========================================================
# STEP 3: STORE — Save to SQLite
# =========================================================
def store(processed_data):
    """Upsert all processed deals into the database."""
    print(f"\n  STEP 3: STORE (upsert to SQLite)")
    print("  " + "-" * 45)

    total = 0
    for cat, products in processed_data.items():
        for p in products:
            db.upsert_deal(p)
            total += 1
        print(f"    {cat}: {len(products)} deals stored")

    print(f"    Total: {total} deals in database")
    return total


# =========================================================
# STEP 4: UPDATE — Expire old + regenerate HTML
# =========================================================
def update():
    """Expire old deals, clean up, regenerate index.html."""
    print(f"\n  STEP 4: UPDATE (expire + regenerate)")
    print("  " + "-" * 45)

    # Expire old deals (>24h)
    expired = db.expire_old_deals()
    print(f"    Expired: {expired} old deals")

    # Delete very old inactive deals (>7 days)
    deleted = db.delete_expired()
    print(f"    Deleted: {deleted} stale deals")

    # Pull active deals from DB
    categories = {}
    for cat in ["gaming", "cosmetics", "fitness", "tech", "home", "outdoors", "kids"]:
        deals = db.get_active_deals(category=cat, min_discount=MIN_DISCOUNT)
        categories[cat] = deals
        print(f"    {cat}: {len(deals)} active deals (>={MIN_DISCOUNT}% off)")

    # Regenerate HTML
    regenerate_html(categories)


def regenerate_html(categories):
    """Rewrite the products JS object in index.html from database."""
    if not os.path.exists(HTML_PATH):
        print("    ERROR: index.html not found")
        return

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Build JS product entries
    sections = []
    for cat in ["gaming", "cosmetics", "fitness", "tech", "home", "outdoors", "kids"]:
        deals = categories.get(cat, [])
        if not deals:
            sections.append(f"  {cat}: []")
            continue

        items = []
        for d in deals:
            title_escaped = d["title"].replace("'", "\\'")
            items.append(
                f"    {{\n"
                f"      title: '{title_escaped}',\n"
                f"      img: '{d['img_url'] if 'img_url' in d else d.get('img', '')}',\n"
                f"      price: {d['price']:.2f}, was: {d['was_price'] if 'was_price' in d else d.get('was', 0):.2f}, discount: {d['discount']}, store: '{d.get('store', 'Amazon')}',\n"
                f"      url: 'https://www.amazon.com/dp/{d['asin']}?tag='+TAG\n"
                f"    }}"
            )
        sections.append(f"  {cat}: [\n" + ",\n".join(items) + "\n  ]")

    new_products_block = "const products={\n" + ",\n".join(sections) + "\n};"

    # Replace old products block (handles both spaced and compact formats)
    pattern = re.compile(r'const products\s*=\s*\{.*?\};', re.DOTALL)
    if pattern.search(html):
        html = pattern.sub(new_products_block, html)
    else:
        print("    WARNING: Could not find products block in HTML")
        return

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    total = sum(len(v) for v in categories.values())
    print(f"    Regenerated index.html with {total} deals")


def show_stats():
    """Display database statistics."""
    stats = db.get_stats()
    print(f"\n  DATABASE STATS")
    print(f"  " + "-" * 35)
    print(f"    Total deals:  {stats['total']}")
    print(f"    Active deals: {stats['active']}")
    for cat_stat in stats["by_category"]:
        print(f"    {cat_stat['category']:12s} {cat_stat['cnt']:3d} deals  avg {cat_stat['avg_disc']:.0f}% off")


# =========================================================
# MAIN
# =========================================================
def main():
    args = sys.argv[1:]

    print("=" * 55)
    print("  SwipeDeals Data Pipeline")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Min discount: {MIN_DISCOUNT}%")
    print("=" * 55)

    if "--stats" in args:
        show_stats()
        return

    if "--refresh" in args:
        print("\n  Refreshing HTML from database...")
        categories = {}
        for cat in ["gaming", "cosmetics", "fitness", "tech", "home", "outdoors", "kids"]:
            categories[cat] = db.get_active_deals(category=cat, min_discount=MIN_DISCOUNT)
        regenerate_html(categories)
        show_stats()
        return

    # Full pipeline
    raw = ingest()          # Step 1
    processed = process(raw) # Step 2
    store(processed)         # Step 3
    update()                 # Step 4

    show_stats()

    print(f"\n{'=' * 55}")
    print("  Pipeline complete! Refresh index.html in browser.")
    print("=" * 55)


if __name__ == "__main__":
    main()
