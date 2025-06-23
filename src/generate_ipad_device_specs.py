import requests
import sqlite3
import re
import difflib
import os
import json
import glob
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List, Tuple
import string

# --- Apple Wiki Data ---
APPLE_WIKI_API_URL = "https://theapplewiki.com/api.php"
APPLE_WIKI_PAGES = {
    "iPad": "List_of_iPads",
}

# Board config to chip mapping from Apple Wiki (copy iPhone mapping for now, but this is likely incomplete for iPad)
BOARD_CHIP_MAPPING = {
    # M4 iPads
    "j720ap": "M4", "j717ap": "M4",
    # M2 iPads
    "j620ap": "M2", "j617ap": "M2",
    # M1 iPads
    "j523ap": "M1", "j517ap": "M1",
    # Older chips
    "j420ap": "A12Z", "j418ap": "A12Z",
    "j320ap": "A12X", "j317ap": "A12X",
    "j207ap": "A10X", "j120ap": "A10X",
    "j98aap": "A9X", "j127ap": "A9X",
    "j171ap": "A10", "j71bap": "A10",
    "j71tap": "A9",
    "j537ap": "M2", "j607ap": "M3", "j637ap": "M3",
    "j507ap": "M2", "j407ap": "M1", "j307ap": "A14",
    "j217ap": "A12", "j81ap": "A8X", "j71ap": "A7",
    "j410ap": "A17 Pro", "j310ap": "A15", "j210ap": "A12",
    "j96ap": "A8", "j85map": "A7", "j85ap": "A7", "p105ap": "A5",
    "j481ap": "A16", "j271ap": "A14", "j181ap": "A13",
    "j171aap": "A12", "p101ap": "A6X", "j1ap": "A5X", "k93ap": "A5"
}

# Expanded manual override maps
MANUAL_CHIP_OVERRIDE = {
    "iPad Pro (11-inch) (2nd generation)": "A12Z",
    "iPad Pro (12.9-inch) (4th generation)": "A12Z",
    "iPad Pro (12.9-inch) (6th generation)": "M2",
    "iPad Pro (11-inch) (4th generation)": "M2",
    "iPad Air (4th generation)": "A14",
    "iPad Air (3rd generation)": "A12",
    "iPad Pro (12.9-inch) (5th generation)": "M1",
}
MANUAL_RAM_OVERRIDE = {
    "iPad (7th generation)": "3 GB",
    "iPad (6th generation)": "2 GB",
    "iPad (5th generation)": "2 GB",
    "iPad (4th generation)": "1 GB",
    "iPad (3rd generation)": "1 GB",
    "iPad 2": "512 MB",
    "iPad Air 2": "2 GB",
    "iPad Pro (11-inch)": "4 GB",
    "iPad Pro (12.9-inch) (3rd generation)": "4 GB",
    "iPad mini (6th generation)": "4 GB",
    "iPad (10th generation)": "4 GB",
    "iPad (9th generation)": "3 GB",
    "iPad (8th generation)": "3 GB",
    "iPad Air (3rd generation)": "3 GB",
    "iPad Air (4th generation)": "4 GB",
    "iPad Air (5th generation)": "8 GB",
    "iPad mini (5th generation)": "3 GB",
    "iPad Pro (12.9-inch) (5th generation)": "8 GB",
}

def get_chip_from_board_config(target: str) -> str:
    if target in BOARD_CHIP_MAPPING:
        return BOARD_CHIP_MAPPING[target]
    for prefix, chip in BOARD_CHIP_MAPPING.items():
        if target.startswith(prefix):
            return chip
    return "Unknown"

def find_xcode_databases() -> List[Tuple[str, str]]:
    databases = []
    standard_path = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"
    if os.path.exists(standard_path):
        databases.append(("Xcode", standard_path))
    beta_paths = glob.glob("/Applications/Xcode-*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db")
    for path in beta_paths:
        version = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))))
        databases.append((version, path))
    return sorted(databases, key=lambda x: x[0])

DEFAULT_DB_PATH = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"

def create_retry_session():
    session = requests.Session()
    retries = Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

def fetch_wiki_text(session, device_type="iPad"):
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
    chip_match = re.search(r'\*\s*CPU:\s*(?:\[\[(.*?)\]\]\s*)?"?([\w\d\s\-+]+)"?', block)
    if not chip_match:
        return "Unknown"
    chip = chip_match.group(2).strip()
    a_chip_match = re.search(r'\bA\d+(?:\s*(?:Pro|X|Bionic|Fusion|B))?\b', chip)
    if a_chip_match:
        return a_chip_match.group(0)
    return "Unknown"

def parse_wiki_devices(raw_text):
    entries = re.split(r"==\s*\[\[(.*?)\]\]\s*==", raw_text)
    data = {}
    for i in range(1, len(entries), 2):
        name = entries[i].strip()
        block = entries[i + 1]
        if name.startswith("File:"): continue
        if not (re.search(r"iPad", name, re.IGNORECASE) or re.search(r"iPad", block, re.IGNORECASE)):
            continue
        chip = extract_chip(block)
        ram_match = re.search(r"\*\s*RAM:\s*(.*?)\s*(?:\n|\r|$)", block, re.IGNORECASE)
        ram = ram_match.group(1).strip() if ram_match else "Unknown"
        ram = standardize_ram(ram)
        data[name] = {
            "chip": chip,
            "ram": ram
        }
    return data

def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> Optional[sqlite3.Connection]:
    if not os.path.exists(db_path):
        print(f"Warning: device_traits.db not found at {db_path}")
        return None
    try:
        return sqlite3.connect(db_path)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def normalize_name(name):
    # Lowercase, remove punctuation, and strip spaces
    return ''.join(c for c in name.lower() if c not in string.punctuation).replace(' ', '')

def get_ipad_family(name: str) -> str:
    """Identifies the family of an iPad model (Pro, Air, mini, or iPad)."""
    name_lower = name.lower()
    if "pro" in name_lower:
        return "pro"
    if "air" in name_lower:
        return "air"
    if "mini" in name_lower:
        return "mini"
    return "ipad"

def generate_device_menu_json(db_path: str = DEFAULT_DB_PATH, ram_map: Dict[str, str] = None, chip_map: Dict[str, str] = None, xcode_version: str = "Xcode") -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    if not conn:
        return { "date_generated": datetime.now().isoformat(), "xcode_version": xcode_version, "total_menu": {} }
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                d.ProductDescription,
                d.ProductType,
                d.Target,
                d.Platform,
                dt.DevicePerformanceMemoryClass AS RAM_Class
            FROM Devices d
            JOIN DeviceTraits dt ON d.DeviceTraitSet = dt.DeviceTraitSetID
            WHERE d.ProductType LIKE 'iPad%'
            ORDER BY d.ProductType DESC
        """)
        menu = {}
        unmatched_chips = []
        unmatched_ram = []
        # Build normalized maps for Wiki data
        norm_chip_map = {normalize_name(k): v for k, v in chip_map.items()} if chip_map else {}
        norm_ram_map = {normalize_name(k): v for k, v in ram_map.items()} if ram_map else {}
        for row in cursor.fetchall():
            model_name = row[0]
            sku = row[1]
            # Strip suffixes like -A, -B from the SKU
            sku = re.sub(r'-[A-Z]$', '', sku)
            ram_db = row[4]
            norm_model_name = normalize_name(model_name)

            # RAM: Check manual override, then Wiki, then DB
            ram = MANUAL_RAM_OVERRIDE.get(model_name)
            if not ram:
                if norm_ram_map:
                    ram = norm_ram_map.get(norm_model_name)
                    if not ram:
                        close = difflib.get_close_matches(norm_model_name, norm_ram_map.keys(), n=1, cutoff=0.8) # Higher cutoff for more accuracy
                        if close:
                            ram = norm_ram_map[close[0]]
            if not ram and ram_db:
                # Fallback to DB if no other source
                try:
                    ram_val = int(ram_db)
                    if ram_val in (4, 6, 8, 12, 16):
                        ram = f"{ram_val} GB"
                    elif ram_val == 3:
                        ram = "3 GB"
                    # ... other DB logic ...
                except Exception:
                    ram = str(ram_db)
            if not ram:
                ram = "Unknown"
                unmatched_ram.append(model_name)
            # CHIP: Check manual override first
            chip = MANUAL_CHIP_OVERRIDE.get(model_name)
            if not chip:
                # Use Wiki chip map with improved fuzzy matching
                if norm_chip_map:
                    # Filter Wiki names by device family for more accurate matching
                    family = get_ipad_family(norm_model_name)
                    family_keys = [k for k in norm_chip_map.keys() if get_ipad_family(k) == family]
                    
                    chip = norm_chip_map.get(norm_model_name)
                    if not chip:
                        # Use a stricter cutoff now that we're matching within the same family
                        close = difflib.get_close_matches(norm_model_name, family_keys, n=1, cutoff=0.8)
                        if close:
                            chip = norm_chip_map[close[0]]
            # Fallback to board config mapping if still not found
            if not chip and row[2] in BOARD_CHIP_MAPPING:
                chip = BOARD_CHIP_MAPPING[row[2]]
            # Remove 'Bionic' from chip name if present
            if chip and isinstance(chip, str):
                chip = chip.replace('Bionic', '').strip()
            if model_name == "iPad Pro (12.9-inch) (5th generation)":
                sku = "iPad13,8"
            menu[model_name] = { 
                "sku": sku, 
                "chip": chip, 
                "ram": ram
            }
        if unmatched_chips:
            print("\nDevices with unmatched chip (no Wiki match):")
            for name in unmatched_chips:
                sku = menu[name]["sku"] if name in menu and "sku" in menu[name] else "?"
                print(f"  {name} (SKU: {sku})")
        if unmatched_ram:
            print("\nDevices with unmatched RAM (no Wiki match):")
            for name in unmatched_ram:
                sku = menu[name]["sku"] if name in menu and "sku" in menu[name] else "?"
                print(f"  {name} (SKU: {sku})")
        return { 
            "date_generated": datetime.now().isoformat(),
            "xcode_version": xcode_version,
            "total_menu": menu 
        }
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return { 
            "date_generated": datetime.now().isoformat(),
            "xcode_version": xcode_version,
            "total_menu": {} 
        }
    finally:
        conn.close()

def check_duplicate_keys(menu_data: Dict[str, Any]) -> List[str]:
    """Check for duplicate keys in the menu data and return list of duplicates."""
    keys = list(menu_data["total_menu"].keys())
    duplicates = []
    seen = set()
    
    for key in keys:
        if key in seen:
            duplicates.append(key)
        else:
            seen.add(key)
    
    return duplicates

def main():
    os.makedirs("apple", exist_ok=True)
    available_dbs = find_xcode_databases()
    if not available_dbs:
        print("Error: No Xcode device_traits.db found!")
        return
    print("Available Xcode databases:")
    for i, (version, path) in enumerate(available_dbs, 1):
        print(f"{i}. {version} ({path})")
    selected_version, selected_path = next(
        ((v, p) for v, p in available_dbs if "Beta" in v or "Developer" in v),
        available_dbs[-1]
    )
    print(f"\nUsing {selected_version} database...")
    print("Fetching Apple Wiki data for iPad...")
    session = create_retry_session()
    wiki_raw = fetch_wiki_text(session, device_type="iPad")
    wiki_devices = parse_wiki_devices(wiki_raw)
    ram_map = { name: meta["ram"] for name, meta in wiki_devices.items() }
    chip_map = { name: meta["chip"] for name, meta in wiki_devices.items() }
    print(f"Generating iPad device menu (from {selected_version}) with RAM details...")
    menu_data = generate_device_menu_json(db_path=selected_path, ram_map=ram_map, chip_map=chip_map, xcode_version=selected_version)
    total_menu = {}
    for model_name, info in menu_data["total_menu"].items():
        total_menu[model_name] = {
            "sku": info["sku"],
            "chip": info["chip"],
            "ram": info["ram"]
        }
    final = {
        "date_generated": menu_data["date_generated"],
        "xcode_version": menu_data["xcode_version"],
        "total_menu": total_menu
    }
    
    # Check for duplicate keys
    duplicates = check_duplicate_keys(final)
    if duplicates:
        print(f"\n⚠️  WARNING: Found {len(duplicates)} duplicate keys:")
        for dup in duplicates:
            print(f"  - {dup}")
        print("This may indicate data quality issues. Please review the source data.")
    else:
        print(f"\n✅ All {len(final['total_menu'])} keys are unique!")
    
    with open("apple/iPad.json", "w") as f:
        json.dump(final, f, indent=2)
    print(f"Done — iPad menu saved to apple/iPad.json (using {selected_version})")
    print("Warning: BOARD_CHIP_MAPPING may be incomplete for iPad. Please review chip assignments.")

    # Final count of devices
    try:
        with open("apple/iPad.json", 'r') as f:
            data = json.load(f)
            count = len(data.get("total_menu", {}))
            print(f"\nTotal iPad models generated: {count}")
    except (FileNotFoundError, json.JSONDecodeError):
        print("\nCould not read file to count devices.")

if __name__ == "__main__":
    main() 