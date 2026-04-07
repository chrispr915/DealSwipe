"""Quick extra scrape for fitness."""

import re, time, random, os
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By

AFFILIATE_TAG = "dealswipes-20"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

EXTRA_QUERIES = [
    "foam roller muscle",
    "pull up bar doorway",
    "workout gloves gym",
    "ab roller wheel",
    "kettlebell weight",
    "pre workout supplement",
]


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


def scrape_deal(driver, query):
    url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    driver.get(url)
    time.sleep(random.uniform(3, 5))
    try:
        results = driver.find_elements(By.CSS_SELECTOR, '[data-component-type="s-search-result"]')
        for result in results[:10]:
            try:
                asin = result.get_attribute("data-asin")
                if not asin or len(asin) != 10: continue
                title_el = result.find_elements(By.CSS_SELECTOR, "h2 span")
                if not title_el: continue
                title = title_el[0].text.strip()
                if not title or len(title) < 10: continue
                img_el = result.find_elements(By.CSS_SELECTOR, "img.s-image")
                img_url = img_el[0].get_attribute("src") if img_el else ""
                price_whole = result.find_elements(By.CSS_SELECTOR, "span.a-price-whole")
                price_frac = result.find_elements(By.CSS_SELECTOR, "span.a-price-fraction")
                if not price_whole: continue
                current = float(price_whole[0].text.replace(",", "").replace(".", ""))
                if price_frac: current += float(f"0.{price_frac[0].text.strip()}")
                original = 0
                old = result.find_elements(By.CSS_SELECTOR, "span.a-price.a-text-price span.a-offscreen")
                if old:
                    try: original = float(old[0].get_attribute("textContent").replace("$", "").replace(",", "").strip())
                    except: pass
                discount = 0
                if original > current: discount = round((1 - current / original) * 100)
                if discount >= 10:
                    return {"title": title[:80], "asin": asin, "price": current, "was": original, "discount": discount, "img": img_url}
            except: continue
    except: pass
    return None


def main():
    print("Scraping extra fitness deals...")
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    fit_match = re.search(r'fitness:\s*\[(.*?)\n  \]', html, re.DOTALL)
    existing = set(re.findall(r'/dp/([A-Z0-9]{10})', fit_match.group(1))) if fit_match else set()
    print(f"  Existing fitness ASINs: {existing}")

    driver = new_driver()
    new_products = []

    for query in EXTRA_QUERIES:
        if len(new_products) >= 2: break
        print(f"  Searching: {query}")
        try:
            p = scrape_deal(driver, query)
            if p and p["asin"] not in existing:
                new_products.append(p)
                existing.add(p["asin"])
                print(f"    FOUND: {p['title'][:50]}... ${p['price']:.2f} -{p['discount']}%")
            else:
                print(f"    Nothing new")
        except Exception as e:
            print(f"    Error: {type(e).__name__}")
            try: driver.quit()
            except: pass
            driver = new_driver()
        time.sleep(random.uniform(2, 4))

    driver.quit()

    if new_products:
        new_entries = ",\n".join(
            f"    {{\n"
            f"      title: '{p['title'].replace(chr(39), chr(92)+chr(39))}',\n"
            f"      img: '{p['img']}',\n"
            f"      price: {p['price']:.2f}, was: {p['was']:.2f}, discount: {p['discount']}, store: 'Amazon',\n"
            f"      url: 'https://www.amazon.com/dp/{p['asin']}?tag=' + AFFILIATE_TAG\n"
            f"    }}"
            for p in new_products
        )
        html = re.sub(r'(fitness:\s*\[.*?)(  \]\n\};)', r'\1,\n' + new_entries + r'\n  ]\n};', html, flags=re.DOTALL)
        with open(HTML_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  Added {len(new_products)} more fitness deals!")
    else:
        print("\n  No extra deals found")


if __name__ == "__main__":
    main()
