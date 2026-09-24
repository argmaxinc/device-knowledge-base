import requests
import sqlite3
import re
import os
import json
import glob
import subprocess
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List, Tuple

# --- AppleDB (MIT licensed) ---
# One JSON index of every Apple device: identifier, marketing name, board config, SoC.
APPLEDB_INDEX_URL = "https://api.appledb.dev/device/main.json"
USER_AGENT = "device-knowledge-base (https://github.com/argmaxinc/device-knowledge-base)"

# Board config to chip mapping, used when AppleDB is unavailable
BOARD_CHIP_MAPPING = {
    # iPhone 18 series and iPhone Duo
    "v63ap": "A20 Pro",  # iPhone 18 Pro
    "v64ap": "A20 Pro",  # iPhone 18 Pro Max
    "v64sap": "A20 Pro", # iPhone 18 Pro Max (iPhone19,7)
    "v68ap": "A20 Pro",  # iPhone Duo
    # iPhone 17 series (2025) - Official Apple specs
    "d23ap": "A19 Pro",  # iPhone Air - confirmed A19 Pro
    "v57ap": "A19",      # iPhone 17 - confirmed A19
    "v54ap": "A19 Pro",  # iPhone 17 Pro Max - confirmed A19 Pro
    "v53ap": "A19 Pro",  # iPhone 17 Pro - confirmed A19 Pro
    "v159ap": "A19",     # iPhone 17e
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
    "t8160": "A20 Pro",  # iPhone 18 Pro / Duo platform (future-proof)
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
    "d331pap": "A12",    # iPhone XS Max (iPhone11,6)
    # iPhone 12 series (all A14)
    "d52gap": "A14",     # iPhone 12 mini
    "d53gap": "A14",     # iPhone 12
    "d53pap": "A14",     # iPhone 12 Pro
    "d54pap": "A14",     # iPhone 12 Pro Max
}

# Marketing names for identifiers that Xcode lists under a placeholder description, used when AppleDB is unavailable
PRODUCT_NAME_OVERRIDE = {
    "iPhone19,4": "iPhone Duo",
}

# Physical RAM per model. Apple does not publish this for iPhone.
MANUAL_RAM_OVERRIDE = {
    "iPhone Duo": "12 GB",
    "iPhone 18 Pro Max": "12 GB",
    "iPhone 18 Pro": "12 GB",
    "iPhone 17e": "8 GB",
    "iPhone Air": "12 GB",
    "iPhone 17": "8 GB",
    "iPhone 17 Pro Max": "12 GB",
    "iPhone 17 Pro": "12 GB",
    "iPhone 16e": "8 GB",
    "iPhone 16 Plus": "8 GB",
    "iPhone 16": "8 GB",
    "iPhone 16 Pro Max": "8 GB",
    "iPhone 16 Pro": "8 GB",
    "iPhone 15 Pro Max": "8 GB",
    "iPhone 15 Pro": "8 GB",
    "iPhone 15 Plus": "6 GB",
    "iPhone 15": "6 GB",
    "iPhone 14 Pro Max": "6 GB",
    "iPhone 14 Pro": "6 GB",
    "iPhone 14 Plus": "6 GB",
    "iPhone 14": "6 GB",
    "iPhone SE (3rd generation)": "4 GB",
    "iPhone 13": "4 GB",
    "iPhone 13 mini": "4 GB",
    "iPhone 13 Pro Max": "6 GB",
    "iPhone 13 Pro": "6 GB",
    "iPhone 12 Pro Max": "6 GB",
    "iPhone 12 Pro": "6 GB",
    "iPhone 12": "4 GB",
    "iPhone 12 mini": "4 GB",
    "iPhone SE (2nd generation)": "3 GB",
    "iPhone 11 Pro Max": "4 GB",
    "iPhone 11 Pro": "4 GB",
    "iPhone 11": "4 GB",
    "iPhone XR": "3 GB",
    "iPhone XS Max": "4 GB",
    "iPhone XS": "4 GB",
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
    other_paths = glob.glob("/Applications/Xcode-*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db")
    for path in other_paths:
        app_match = re.search(r"/Applications/([^/]+\.app)/", path)
        version = app_match.group(1) if app_match else path
        databases.append((version, path))
    
    return sorted(databases, key=lambda x: x[0])

# --- Xcode device_traits.db ---
DEFAULT_DB_PATH = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"

def get_xcode_version_from_db_path(db_path: str) -> str:
    """Extract the Xcode version string from the Xcode app bundle given a device_traits.db path."""
    xcode_root = db_path.split("/Contents/")[0] + "/Contents"
    xcodebuild_path = os.path.join(xcode_root, "Developer/usr/bin/xcodebuild")
    if os.path.exists(xcodebuild_path):
        try:
            output = subprocess.check_output([xcodebuild_path, "-version"], universal_newlines=True)
            lines = output.strip().split("\n")
            if len(lines) >= 2:
                version = lines[0].replace("Xcode ", "Version ")
                build = lines[1].replace("Build version ", "")
                return f"{version} ({build})"
        except Exception as e:
            return f"Unknown (error: {e})"
    return "Unknown"

def xcode_version_key(db_path: str) -> Tuple[int, ...]:
    """Numeric Xcode version for a device_traits.db path, for picking the newest install."""
    match = re.search(r"Version (\d+(?:\.\d+)*)", get_xcode_version_from_db_path(db_path))
    return tuple(int(n) for n in match.group(1).split(".")) if match else (0,)

# --- Helper functions for AppleDB (device names and chips) ---
def create_retry_session():
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retries = Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

def fetch_appledb_index(session) -> Dict[str, Dict[str, Any]]:
    """Fetch the AppleDB device index and key it by identifier (e.g. 'iPhone19,2')."""
    resp = session.get(APPLEDB_INDEX_URL, timeout=60)
    resp.raise_for_status()
    index = {}
    for entry in resp.json():
        identifiers = entry.get("identifier") or []
        if isinstance(identifiers, str):
            identifiers = [identifiers]
        for identifier in identifiers:
            index.setdefault(identifier, entry)
    return index

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

def generate_device_menu_json(db_path: str = DEFAULT_DB_PATH, appledb: Dict[str, Dict[str, Any]] = None, xcode_version: str = "Xcode") -> Dict[str, Any]:
    """
    Generate a JSON menu of all iPhone devices (XR/XS and newer) with their SKUs, chips, and RAM.
    
    Args:
        db_path: Path to device_traits.db
        appledb: AppleDB device index keyed by identifier (names and chips)
        xcode_version: Version of Xcode being used (for metadata)
    """
    appledb = appledb or {}
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
        unknown_ram = []
        chip_mismatches = []
        for row in cursor.fetchall():
            model_name = row[0]
            sku = row[1]
            target = row[2]
            platform = row[3]
            # Print board config for iPhone 12 series
            if model_name in ["iPhone 12", "iPhone 12 mini", "iPhone 12 Pro", "iPhone 12 Pro Max"]:
                print(f"DEBUG: {model_name} (SKU: {sku}) has board config: {target}")
            match = re.match(r"iPhone(\d+),(\d+)", sku)
            if not match:
                continue
            major_version = int(match.group(1))
            if major_version < 11:  # Include iPhone 11 and newer (iPhone11,x through iPhone18,x)
                continue
            entry = appledb.get(sku, {})
            # Xcode lists unreleased hardware under a placeholder description; AppleDB has the marketing name
            if model_name == "iPhone":
                model_name = entry.get("name") or PRODUCT_NAME_OVERRIDE.get(sku, model_name)
            sku_key = (major_version, int(match.group(2)))
            # Some models ship under more than one identifier (regional variants).
            # Keep the lowest identifier as the canonical SKU for that model name.
            if model_name in menu and menu[model_name]["_sku_key"] <= sku_key:
                continue
            board_chip = get_chip_from_board_config(target)
            chip = entry.get("soc") or board_chip
            if chip == "Unknown":
                unknown_chips[model_name] = target
            elif board_chip not in ("Unknown", chip):
                chip_mismatches.append(f"{model_name} ({sku}): AppleDB {chip}, board config {board_chip}")
            ram = MANUAL_RAM_OVERRIDE.get(model_name)
            if not ram:
                ram = "Unknown"
                unknown_ram.append(model_name)
            menu[model_name] = { 
                "sku": sku, 
                "chip": chip, 
                "ram": ram,
                "board_config": target,
                "_sku_key": sku_key
            }
        if unknown_chips:
            print("\nDevices with unknown chips (board configs):")
            for model, board_config in unknown_chips.items():
                print(f"{model}: {board_config}")
        if chip_mismatches:
            print("\nChip disagreements between AppleDB and BOARD_CHIP_MAPPING (AppleDB used):")
            for line in chip_mismatches:
                print(f"  {line}")
        if unknown_ram:
            print("\nDevices missing from MANUAL_RAM_OVERRIDE:")
            for model in unknown_ram:
                print(f"  {model}")
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
    
    # Use the latest available version
    selected_version, selected_path = max(available_dbs, key=lambda vp: xcode_version_key(vp[1]))
    print(f"\nUsing {selected_version} database...")
    
    # Fetch AppleDB data (for names and chip details)
    print("Fetching AppleDB device index...")
    try:
        appledb = fetch_appledb_index(create_retry_session())
        print(f"Found {len(appledb)} identifiers in AppleDB")
    except Exception as e:
        print(f"Warning: Could not fetch AppleDB, falling back to BOARD_CHIP_MAPPING: {e}")
        appledb = {}
    
    # Generate the device menu JSON (using device_traits.db and AppleDB)
    print(f"Generating iPhone device menu (from {selected_version}) with RAM details...")
    xcode_version_str = get_xcode_version_from_db_path(selected_path)
    menu_data = generate_device_menu_json(db_path=selected_path, appledb=appledb, xcode_version=xcode_version_str)
    
    # Add 'ram' to each device in total_menu
    # Sorted newest identifier first
    ordered = sorted(menu_data["total_menu"].items(), key=lambda kv: kv[1]["_sku_key"], reverse=True)
    total_menu = {}
    for model_name, info in ordered:
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
