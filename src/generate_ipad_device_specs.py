import requests
import sqlite3
import re
import os
import json
import glob
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List, Tuple
import subprocess

# --- AppleDB (MIT licensed) ---
# One JSON index of every Apple device: identifier, marketing name, board config, SoC.
APPLEDB_INDEX_URL = "https://api.appledb.dev/device/main.json"
USER_AGENT = "device-knowledge-base (https://github.com/argmaxinc/device-knowledge-base)"

# Board config to chip mapping, used when AppleDB is unavailable (adapted from iPhone mapping, but this may be incomplete for iPad)
BOARD_CHIP_MAPPING = {
    # M5 iPads (iPad Pro, 2025)
    "j817ap": "M5", "j818ap": "M5", "j820ap": "M5", "j821ap": "M5",
    # M4 iPads
    "j720ap": "M4", "j717ap": "M4", "j718ap": "M4", "j721ap": "M4",
    "j707ap": "M4", "j708ap": "M4", "j737ap": "M4", "j738ap": "M4",
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
    "iPad (8th generation)": "A12",
}
# Physical RAM per model (base configuration). Apple only publishes this for recent iPads.
MANUAL_RAM_OVERRIDE = {
    "iPad (7th generation)": "3 GB",
    "iPad (6th generation)": "2 GB",
    "iPad (5th generation)": "2 GB",
    "iPad (4th generation)": "1 GB",
    "iPad (3rd generation)": "1 GB",
    "iPad 2": "512 MB",
    "iPad Air 2": "2 GB",
    "iPad Pro (11-inch)": "4 GB",
    "iPad Pro (11-inch) (2nd generation)": "6 GB",
    "iPad Pro (12.9-inch) (3rd generation)": "4 GB",
    "iPad Pro (12.9-inch) (4th generation)": "6 GB",
    "iPad mini (6th generation)": "4 GB",
    "iPad mini (A17 Pro)": "8 GB",
    "iPad (10th generation)": "4 GB",
    "iPad (9th generation)": "3 GB",
    "iPad (8th generation)": "3 GB",
    "iPad Air (3rd generation)": "3 GB",
    "iPad Air (4th generation)": "4 GB",
    "iPad Air (5th generation)": "8 GB",
    "iPad Air 11-inch (M2)": "8 GB",
    "iPad Air 13-inch (M2)": "8 GB",
    "iPad Air 11-inch (M3)": "8 GB",
    "iPad Air 13-inch (M3)": "8 GB",
    "iPad mini (5th generation)": "3 GB",
    "iPad Pro (12.9-inch) (5th generation)": "8 GB",
    "iPad Pro (11-inch) (3rd generation)": "8 GB",
    "iPad Pro (11-inch) (4th generation)": "8 GB",
    "iPad Pro (12.9-inch) (6th generation)": "8 GB",
    "iPad Pro 11-inch (M4)": "8 GB",
    "iPad Pro 13-inch (M4)": "8 GB",
    "iPad (A16)": "8 GB",
    # Base configuration (iPad Pro (M5) ships 16 GB at 1 TB and above)
    "iPad Pro 11-inch (M5)": "12 GB",
    "iPad Pro 13-inch (M5)": "12 GB",
    "iPad Air 11-inch (M4)": "12 GB",
    "iPad Air 13-inch (M4)": "12 GB",
}

MANUAL_SKU_OVERRIDE = {
    "iPad Pro (12.9-inch) (5th generation)": "iPad13,8 iPad13,9 iPad13,10 iPad13,11"
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
    other_paths = glob.glob("/Applications/Xcode-*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db")
    for path in other_paths:
        app_match = re.search(r"/Applications/([^/]+\.app)/", path)
        version = app_match.group(1) if app_match else path
        databases.append((version, path))
    return sorted(databases, key=lambda x: x[0])

DEFAULT_DB_PATH = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"

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
    """Fetch the AppleDB device index and key it by identifier (e.g. 'iPad17,1')."""
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

def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> Optional[sqlite3.Connection]:
    if not os.path.exists(db_path):
        print(f"Warning: device_traits.db not found at {db_path}")
        return None
    try:
        return sqlite3.connect(db_path)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def is_chip_at_least_a12(chip: str) -> bool:
    """Return True if chip is A12 or newer, or any M-series chip."""
    if not chip or chip == "Unknown":
        return False
    chip = chip.strip().upper()
    if chip.startswith("M"):
        return True
    match = re.match(r"A(\d+)", chip)
    if match:
        try:
            return int(match.group(1)) >= 12
        except Exception:
            return False
    return False

def get_xcode_version_from_db_path(db_path: str) -> str:
    """Extract the Xcode version string from the Xcode app bundle given a device_traits.db path."""
    # Find the Xcode.app root from the db_path
    xcode_root = db_path.split("/Contents/")[0] + "/Contents"
    xcodebuild_path = os.path.join(xcode_root, "Developer/usr/bin/xcodebuild")
    if os.path.exists(xcodebuild_path):
        try:
            output = subprocess.check_output([xcodebuild_path, "-version"], universal_newlines=True)
            # Usually returns: 'Xcode 16.3\nBuild version 16E140\n'
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

def generate_device_menu_json(db_path: str = DEFAULT_DB_PATH, appledb: Dict[str, Dict[str, Any]] = None, xcode_version: str = "Xcode") -> Dict[str, Any]:
    appledb = appledb or {}
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
        # Group rows by ProductDescription
        device_rows = {}
        for row in cursor.fetchall():
            model_name = row[0]
            if model_name not in device_rows:
                device_rows[model_name] = []
            device_rows[model_name].append(row)
        menu = {}
        unmatched_chips = []
        unmatched_ram = []
        chip_mismatches = []
        for model_name, rows in device_rows.items():
            skus = []
            chip = None
            ram = None
            for row in rows:
                sku = row[1]
                sku = re.sub(r'-[A-Z]$', '', sku)
                if sku not in skus:
                    skus.append(sku)
                ram_db = row[4]
                # RAM: Check manual override, then DB
                if ram is None:
                    ram = MANUAL_RAM_OVERRIDE.get(model_name)
                    if not ram and ram_db:
                        try:
                            ram_val = int(ram_db)
                            if ram_val in (4, 6, 8, 12, 16):
                                ram = f"{ram_val} GB"
                            elif ram_val == 3:
                                ram = "3 GB"
                        except Exception:
                            ram = str(ram_db)
                    if not ram:
                        ram = "Unknown"
                        unmatched_ram.append(model_name)
                # CHIP: AppleDB first, then manual override, then board config
                if chip is None:
                    local_chip = MANUAL_CHIP_OVERRIDE.get(model_name) or get_chip_from_board_config(row[2])
                    chip = appledb.get(sku, {}).get("soc") or local_chip
                    if chip == "Unknown":
                        chip = None
                    elif local_chip not in ("Unknown", chip):
                        chip_mismatches.append(f"{model_name} ({sku}): AppleDB {chip}, local mapping {local_chip}")
            if chip is None:
                unmatched_chips.append(model_name)
            if model_name in MANUAL_SKU_OVERRIDE:
                skus = MANUAL_SKU_OVERRIDE[model_name].split()
            # Sort SKUs by the numeric part after the comma
            def sku_sort_key(s):
                m = re.match(r"iPad(\d+),(\d+)", s)
                return (int(m.group(1)), int(m.group(2))) if m else (s,)
            skus = sorted(skus, key=sku_sort_key)
            # Only include A12 or newer, or M-series chips
            if not is_chip_at_least_a12(chip):
                continue
            menu[model_name] = {
                "sku": skus,
                "chip": chip,
                "ram": ram
            }
        if unmatched_chips:
            print("\nDevices with unmatched chip (no AppleDB or local match):")
            for name in unmatched_chips:
                print(f"  {name}")
        if chip_mismatches:
            print("\nChip disagreements between AppleDB and local mapping (AppleDB used):")
            for line in chip_mismatches:
                print(f"  {line}")
        if unmatched_ram:
            print("\nDevices with unmatched RAM (missing from MANUAL_RAM_OVERRIDE):")
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
    # Use the latest available version
    selected_version, selected_path = max(available_dbs, key=lambda vp: xcode_version_key(vp[1]))
    print(f"\nUsing {selected_version} database...")
    print("Fetching AppleDB device index...")
    try:
        appledb = fetch_appledb_index(create_retry_session())
        print(f"Found {len(appledb)} identifiers in AppleDB")
    except Exception as e:
        print(f"Warning: Could not fetch AppleDB, falling back to local chip mappings: {e}")
        appledb = {}
    print(f"Generating iPad device menu (from {selected_version}) with RAM details...")
    xcode_version_str = get_xcode_version_from_db_path(selected_path)
    menu_data = generate_device_menu_json(db_path=selected_path, appledb=appledb, xcode_version=xcode_version_str)
    # Newest identifier first, so the file reads top-down from the latest device
    def first_sku_key(item):
        m = re.match(r"iPad(\d+),(\d+)", item[1]["sku"][0])
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    total_menu = {}
    for model_name, info in sorted(menu_data["total_menu"].items(), key=first_sku_key, reverse=True):
        total_menu[model_name] = {
            "sku": info["sku"],
            "chip": info["chip"],
            "ram": info["ram"]
        }
    final = {
        "date_generated": menu_data["date_generated"],
        "xcode_version": xcode_version_str,
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
