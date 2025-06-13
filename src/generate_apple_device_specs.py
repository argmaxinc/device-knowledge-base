import requests
import pandas as pd
import sqlite3
import re
import difflib
import os
import json
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Wikipedia Release Dates ---
WIKI_PAGES = {
    "iPhone": "https://en.wikipedia.org/wiki/List_of_iPhone_models",
    # Extend for iPad, Mac, etc.
}

def fetch_wikipedia_release_dates(device_type):
    url = WIKI_PAGES[device_type]
    tables = pd.read_html(url)
    model_col = release_col = None
    device_table = None
    for idx, table in enumerate(tables):
        cols = table.columns
        if not (hasattr(cols, 'levels') and len(cols.levels) == 2):
            try:
                multi_tables = pd.read_html(url, header=[0,1])
                if idx < len(multi_tables):
                    table = multi_tables[idx]
                    cols = table.columns
            except Exception:
                pass
        if hasattr(cols, 'levels') and len(cols.levels) == 2:
            for c in cols:
                if 'Model' in str(c[0]) and model_col is None:
                    model_col = c
                if 'Release' in str(c[0]) and 'Date' in str(c[1]) and release_col is None:
                    release_col = c
            if model_col and release_col:
                device_table = table
                break
        else:
            if any('Model' in str(c) for c in cols) and any('Release date' in str(c) for c in cols):
                model_col = [c for c in cols if 'Model' in str(c)][0]
                release_col = [c for c in cols if 'Release date' in str(c)][0]
                device_table = table
                break
    if device_table is None:
        raise RuntimeError(f"Could not find the {device_type} models table!")
    df_release = device_table[[model_col, release_col]].copy()
    df_release.columns = ['Device', 'Release Date']
    pretty = {}
    for _, row in df_release.iterrows():
        key = row['Device']
        value = row['Release Date']
        value = str(value).replace('\u00a0', ' ').strip()
        match = re.search(r'([A-Za-z]+\s+\d{1,2},\s+\d{4})', value)
        if match:
            value = match.group(1)
        pretty[key] = value
    return pretty

# --- Apple Wiki Data ---
def create_retry_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

APPLE_WIKI_API_URL = "https://theapplewiki.com/api.php"
APPLE_WIKI_PAGES = {
    "iPhone": "List_of_iPhones",
    # Extend for iPad, Mac, etc.
}

def fetch_wiki_text(session, device_type="iPhone"):
    params = {
        "action": "query",
        "titles": APPLE_WIKI_PAGES[device_type],
        "prop": "revisions",
        "rvprop": "content",
        "format": "json"
    }
    resp = session.get(APPLE_WIKI_API_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    pages = data["query"]["pages"]
    for page_id in pages:
        if "revisions" in pages[page_id]:
            return pages[page_id]["revisions"][0]["*"]
    raise RuntimeError("Wiki text not found!")

def standardize_ram(ram_str):
    if ram_str == "Unknown":
        return ram_str
    ram_str = ram_str.strip().upper()
    match = re.search(r'(\d+)\s*(GB|MB|G|M)(?:\s*(?:LPDDR\d+X)?)?', ram_str)
    if not match:
        return ram_str
    number, unit = match.groups()
    if unit in ['G', 'GB']:
        unit = 'GB'
    elif unit in ['M', 'MB']:
        unit = 'MB'
    return f"{number} {unit}"

def extract_chip(block):
    chip_match = re.search(r'\*\s*CPU:\s*(?:\[\[(.*?)\]\]\s*)?\"?([\w\d\s\-+]+)\"?', block)
    if not chip_match:
        return "Unknown"
    chip = chip_match.group(2).strip()
    a_chip_match = re.search(r'\bA\d+(?:\s*(?:Pro|X|Bionic|Fusion|B))?\b', chip)
    if a_chip_match:
        return a_chip_match.group(0)
    if "S5L8900" in chip:
        return "S5L8900"
    elif "S5L8920" in chip:
        return "S5L8920"
    elif "S5L8930" in chip:
        return "S5L8930"
    elif "S5L8940" in chip:
        return "S5L8940"
    elif "S5L8942" in chip:
        return "S5L8942"
    elif "S5L8945" in chip:
        return "S5L8945"
    elif "S5L8950" in chip:
        return "S5L8950"
    elif "S5L8955" in chip:
        return "S5L8955"
    return "Unknown"

def parse_wiki_devices(raw_text):
    entries = re.split(r"==\s*\[\[(.*?)\]\]\s*==", raw_text)
    data = {}
    for i in range(1, len(entries), 2):
        name = entries[i].strip()
        block = entries[i + 1]
        if name.startswith("File:"): continue
        chip = extract_chip(block)
        ram_match = re.search(r"\*\s*RAM:\s*(.*?)\s*(?:\n|\r|$)", block, re.IGNORECASE)
        ram = ram_match.group(1).strip() if ram_match else "Unknown"
        ram = standardize_ram(ram)
        data[name] = {
            "chip": chip,
            "ram": ram
        }
    return data

def fetch_xcode_sku_map(db_path="/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"):
    if not os.path.exists(db_path):
        print(f"Warning: Xcode device_traits.db not found at {db_path}")
        return {}
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT ProductDescription, ProductType 
        FROM Devices 
        WHERE ProductType LIKE 'iPhone%'
    """, conn)
    conn.close()
    result = {}
    for _, row in df.iterrows():
        name = row["ProductDescription"]
        sku = row["ProductType"]
        result[name] = sku
    return result

def main():
    os.makedirs("apple", exist_ok=True)
    # Step 1: Fetch release dates
    print("Fetching iPhone release dates from Wikipedia...")
    release_dates = fetch_wikipedia_release_dates("iPhone")
    # Step 2: Fetch Apple Wiki data
    print("Fetching Apple Wiki data for iPhone...")
    session = create_retry_session()
    wiki_raw = fetch_wiki_text(session, device_type="iPhone")
    wiki_devices = parse_wiki_devices(wiki_raw)
    # Step 3: Fetch SKU map
    print("Querying local Xcode device_traits.db for iPhone...")
    sku_map = fetch_xcode_sku_map()
    # Step 4: Combine data
    print("Combining data...")
    total = {}
    for name, meta in wiki_devices.items():
        sku = sku_map.get(name)
        if not sku:
            close = difflib.get_close_matches(name, sku_map.keys(), n=1, cutoff=0.85)
            if close:
                sku = sku_map[close[0]]
            else:
                sku = "Unknown"
        release_date = release_dates.get(name)
        if not release_date:
            close = difflib.get_close_matches(name, release_dates.keys(), n=1, cutoff=0.85)
            if close:
                release_date = release_dates[close[0]]
            else:
                release_date = "Unknown"
        total[name] = {
            "sku": sku,
            "chip": meta["chip"],
            "ram": meta["ram"],
            "release_date": release_date
        }
    final = {
        "date_generated": datetime.now().isoformat(),
        "devices": total
    }
    # Step 5: Save to apple/iPhone.json
    with open("apple/iPhone.json", "w") as f:
        json.dump(final, f, indent=2)
    print("Done — iPhone data saved to apple/iPhone.json")

if __name__ == "__main__":
    main() 