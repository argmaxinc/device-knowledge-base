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

# --- Apple Wiki Data ---
APPLE_WIKI_API_URL = "https://theapplewiki.com/api.php"
APPLE_WIKI_PAGES = {
    "iPhone": "List_of_iPhones",
    # Extend for iPad, Mac, etc.
}

# Board config to chip mapping from Apple Wiki
BOARD_CHIP_MAPPING = {
    # iPhone 17 series (2025) - Official Apple specs
    "d23ap": "A19 Pro",  # iPhone Air - confirmed A19 Pro
    "v57ap": "A19",      # iPhone 17 - confirmed A19
    "v54ap": "A19 Pro",  # iPhone 17 Pro Max - confirmed A19 Pro
    "v53ap": "A19 Pro",  # iPhone 17 Pro - confirmed A19 Pro
    # iPhone 16 series
    "d94ap": "A18 Pro",  # iPhone 16 Pro Max
    "d93ap": "A18 Pro",  # iPhone 16 Pro
    "d48ap": "A18",      # iPhone 16 Plus
    "d47ap": "A18",      # iPhone 16
    "v59ap": "A18",      # iPhone 16e
    # iPhone 15 series
    "d84ap": "A17 Pro",  # iPhone 15 Pro Max
    "d83ap": "A17 Pro",  # iPhone 15 Pro
    "d38ap": "A16",      # iPhone 15 Plus
    "d37ap": "A16",      # iPhone 15
    # iPhone 14 series
    "d28ap": "A15",      # iPhone 14 Plus
    "d27ap": "A15",      # iPhone 14
    # iPhone 13 series
    "d17ap": "A15",      # iPhone 13
    "d16ap": "A15",      # iPhone 13 mini
    # iPhone SE (3rd gen)
    "d49ap": "A15",      # iPhone SE (3rd generation)
    # iPhone SE (2nd gen)
    "d79ap": "A13",      # iPhone SE (2nd generation)
    # iPhone 11 series (all A13)
    "n104ap": "A13",      # iPhone 11
    "d321": "A13",       # iPhone 11 (legacy)
    "d421ap": "A13",     # iPhone 11 Pro (updated board config)
    "d431ap": "A13",     # iPhone 11 Pro Max (updated board config)
    # iPhone XR
    "n841ap": "A12",      # iPhone XR
    # Existing mappings (updated for iPhone 12 series)
    "t8150": "A19",      # iPhone 17 series platform - A19/A19 Pro
    "t8140": "A18 Pro",  # iPhone 16 Pro/Pro Max (future-proof)
    "t8140a": "A18",     # iPhone 16/16 Plus (future-proof)
    "t8130": "A17 Pro",  # iPhone 15 Pro/Pro Max (future-proof)
    "t8120": "A16",      # iPhone 15/15 Plus (future-proof)
    "d63": "A15",        # iPhone 14/14 Plus (legacy)
    "d64": "A15",        # iPhone 14/14 Plus (legacy)
    "d73": "A16",        # iPhone 14 Pro
    "d74": "A16",        # iPhone 14 Pro Max
    "d52g": "A15",       # iPhone 13/13 mini (legacy)
    "d53g": "A15",       # iPhone 13/13 mini (legacy)
    "d53p": "A15",       # iPhone 13 Pro (legacy)
    "d54p": "A15",       # iPhone 13 Pro Max (legacy)
    "d421": "A14",       # iPhone 12/12 mini
    "d431": "A14",       # iPhone 12 Pro/Pro Max
    "d321ap": "A12",     # iPhone XR
    "d331ap": "A12",     # iPhone XS/XS Max
    # iPhone 12 series (all A14)
    "d52gap": "A14",     # iPhone 12 mini
    "d53gap": "A14",     # iPhone 12
    "d53pap": "A14",     # iPhone 12 Pro
    "d54pap": "A14",     # iPhone 12 Pro Max
}

def get_chip_from_board_config(target: str) -> str:
    """
    Get the chip name from the board config (target).
    Returns 'Unknown' if no mapping is found.
    """
    # Try exact match first
    if target in BOARD_CHIP_MAPPING:
        return BOARD_CHIP_MAPPING[target]
    
    # Try prefix match (e.g., 'd83' for iPhone 15 series)
    for prefix, chip in BOARD_CHIP_MAPPING.items():
        if target.startswith(prefix):
            return chip
    
    return "Unknown"

def find_xcode_databases() -> List[Tuple[str, str]]:
    """
    Find all available Xcode device_traits.db files.
    Returns a list of tuples (xcode_version, db_path)
    """
    databases = []
    # Check standard Xcode
    standard_path = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"
    if os.path.exists(standard_path):
        databases.append(("Xcode", standard_path))
    
    # Check additional Xcode installations
    beta_paths = glob.glob("/Applications/Xcode-*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db")
    beta_paths.extend(glob.glob("/Applications/Xcode copy*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"))
    for path in beta_paths:
        app_name = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))))
        # Assign clean version names
        if "copy 2" in app_name.lower():
            version = "Xcode 26.0"
        elif "copy" in app_name.lower():
            version = "Xcode 16.4"
        else:
            version = app_name
        databases.append((version, path))
    
    return sorted(databases, key=lambda x: x[0])

# --- Xcode device_traits.db ---
DEFAULT_DB_PATH = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"

# --- Helper functions for Apple Wiki (fetching RAM and chip details) ---
def create_retry_session():
    session = requests.Session()
    retries = Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

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
        # Only include iPhone XR/XS and newer (iPhone 11 or higher)
        # Match 'iPhone XR', 'iPhone XS', or 'iPhone <number>' where number >= 11
        if not (re.search(r"iPhone\s*(XR|XS|1[1-9]|[2-9][0-9])", name, re.IGNORECASE) or re.search(r"iPhone\s*(XR|XS|1[1-9]|[2-9][0-9])", block, re.IGNORECASE)):
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

# --- Helper functions for Xcode device_traits.db (menu JSON generation) ---
def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> Optional[sqlite3.Connection]:
    if not os.path.exists(db_path):
        print(f"Warning: device_traits.db not found at {db_path}")
        return None
    try:
        return sqlite3.connect(db_path)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def generate_device_menu_json(db_path: str = DEFAULT_DB_PATH, ram_map: Dict[str, str] = None, xcode_version: str = "Xcode") -> Dict[str, Any]:
    """
    Generate a JSON menu of all iPhone devices (XR/XS and newer) with their SKUs, chips, and RAM (using ram_map if provided).
    
    Args:
        db_path: Path to device_traits.db
        ram_map: Dictionary mapping device names to RAM specifications
        xcode_version: Version of Xcode being used (for metadata)
    """
    conn = get_db_connection(db_path)
    if not conn:
        return { "date_generated": datetime.now().isoformat(), "xcode_version": xcode_version, "total_menu": {} }
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                ProductDescription,
                ProductType,
                Target,
                Platform
            FROM Devices 
            WHERE ProductType LIKE 'iPhone%'
            ORDER BY ProductType DESC
        """)
        menu = {}
        unknown_chips = {}
        for row in cursor.fetchall():
            model_name = row[0]
            sku = row[1]
            target = row[2]
            platform = row[3]
            # Print board config for iPhone 12 series
            if model_name in ["iPhone 12", "iPhone 12 mini", "iPhone 12 Pro", "iPhone 12 Pro Max"]:
                print(f"DEBUG: {model_name} (SKU: {sku}) has board config: {target}")
            match = re.match(r"iPhone(\d+),", sku)
            if not match:
                continue
            major_version = int(match.group(1))
            if major_version < 11:  # Include iPhone 11 and newer (iPhone11,x through iPhone18,x)
                continue
            chip = get_chip_from_board_config(target)
            if chip == "Unknown":
                unknown_chips[model_name] = target
            ram = "Unknown"
            # Get RAM from Apple Wiki for all devices (including iPhone 17 series)
            if ram_map:
                ram = ram_map.get(model_name)
                if not ram:
                    close = difflib.get_close_matches(model_name, ram_map.keys(), n=1, cutoff=0.85)
                    if close:
                        ram = ram_map[close[0]]
            
            # For iPhone 17 series, default to 8 GB if no RAM data found
            if major_version == 18 and (ram == "Unknown" or ram is None):
                ram = "8 GB"
            menu[model_name] = { 
                "sku": sku, 
                "chip": chip, 
                "ram": ram,
                "board_config": target
            }
        if unknown_chips:
            print("\nDevices with unknown chips (board configs):")
            for model, board_config in unknown_chips.items():
                print(f"{model}: {board_config}")
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

# --- Main function ---
def main():
    os.makedirs("apple", exist_ok=True)
    
    # Find available Xcode databases
    available_dbs = find_xcode_databases()
    if not available_dbs:
        print("Error: No Xcode device_traits.db found!")
        return
    
    print("Available Xcode databases:")
    for i, (version, path) in enumerate(available_dbs, 1):
        print(f"{i}. {version} ({path})")
    
    # Use Xcode 26.0 first, then other versions
    selected_version, selected_path = next(
        ((v, p) for v, p in available_dbs if "26.0" in v),
        next(((v, p) for v, p in available_dbs if "Developer" in v), available_dbs[-1])
    )
    print(f"\nUsing {selected_version} database...")
    
    # Fetch Apple Wiki data (for chip and RAM details)
    print("Fetching Apple Wiki data for iPhone...")
    session = create_retry_session()
    wiki_raw = fetch_wiki_text(session, device_type="iPhone")
    wiki_devices = parse_wiki_devices(wiki_raw)
    
    # Generate a RAM map (from Apple Wiki) for merging into the menu JSON
    ram_map = { name: meta["ram"] for name, meta in wiki_devices.items() }
    
    # Generate the device menu JSON (using device_traits.db and ram_map)
    print(f"Generating iPhone device menu (from {selected_version}) with RAM details...")
    menu_data = generate_device_menu_json(db_path=selected_path, ram_map=ram_map, xcode_version=selected_version)
    
    # Add 'ram' to each device in total_menu
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
    
    with open("apple/iPhone.json", "w") as f:
        json.dump(final, f, indent=2)
    print(f"Done — iPhone menu saved to apple/iPhone.json (using {selected_version})")

if __name__ == "__main__":
    main() 