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
import subprocess

# --- Apple Wiki Data ---
# This script generates Mac device specifications for M1 and newer models only
APPLE_WIKI_API_URL = "https://theapplewiki.com/api.php"
APPLE_WIKI_PAGES = {
    "Mac": "List_of_Macs",
}

# Board config to chip mapping for Macs (M1 and newer only)
BOARD_CHIP_MAPPING = {
    # M4 Macs
    "j720ap": "M4", "j717ap": "M4",
    # M3 Macs
    "j620ap": "M3", "j617ap": "M3", "j637ap": "M3",
    # M2 Macs
    "j523ap": "M2", "j517ap": "M2", "j607ap": "M2",
    # M1 Macs
    "j420ap": "M1", "j418ap": "M1", "j407ap": "M1"
}

# Manual chip overrides for Macs
MANUAL_CHIP_OVERRIDE = {
    # M4 Series (2024-2025) - Updated to match the image exactly
    "MacBook Air (2024, M4)": "M4",
    "MacBook Pro (2024, M4)": "M4",
    "Mac mini (2024, M4)": "M4",
    "iMac (2024, M4)": "M4",
    
    # M3 Series (2023-2024) - Updated to match the image exactly
    "iMac (2023, M3)": "M3",
    "MacBook Pro (2023, M3)": "M3",
    "MacBook Air (2024, M3)": "M3",
    
    # M2 Series (2022-2023) - Updated to match the image exactly
    "MacBook Air (2022, M2)": "M2",
    "MacBook Pro (2022, M2)": "M2",
    "Mac Mini (2023, M2)": "M2",
    "Mac Pro (2023, M2)": "M2",
    "Mac Studio (2022, M2)": "M2 Ultra",
    
    # M1 Series (2020-2022)
    "MacBook Pro (2020, M1)": "M1",
    "MacBook Air (2020, M1)": "M1",
    "Mac Mini (2020, M1)": "M1",
    "iMac (2021, M1)": "M1",
    "Mac Studio (2022, M1)": "M1",
    
    # Additional high-end models from table
    "Mac Studio (M4 Max)": "M4 Max",
    "Mac Studio (M3 Ultra)": "M3 Ultra"
}

# Manual RAM overrides for Macs
MANUAL_RAM_OVERRIDE = {
    # M4 Series (2024-2025) - Updated to match the image exactly
    "MacBook Air (2024, M4)": "8 GB",
    "MacBook Pro (2024, M4)": "8 GB",
    "Mac mini (2024, M4)": "8 GB",
    "iMac (2024, M4)": "8 GB",
    
    # M3 Series (2023-2024) - Updated to match the image exactly
    "iMac (2023, M3)": "8 GB",
    "MacBook Pro (2023, M3)": "8 GB",
    "MacBook Air (2024, M3)": "8 GB",
    
    # M2 Series (2022-2023) - Updated to match the image exactly
    "MacBook Air (2022, M2)": "8 GB",
    "MacBook Pro (2022, M2)": "8 GB",
    "Mac Mini (2023, M2)": "8 GB",
    "Mac Pro (2023, M2)": "64 GB",
    "Mac Studio (2022, M2)": "32 GB",
    
    # M1 Series (2020-2022)
    "MacBook Pro (2020, M1)": "8 GB",
    "MacBook Air (2020, M1)": "8 GB",
    "Mac Mini (2020, M1)": "8 GB",
    "iMac (2021, M1)": "8 GB",
    "Mac Studio (2022, M1)": "32 GB",
    
    # Additional high-end models from table
    "Mac Studio (M4 Max)": "38 GB",
    "Mac Studio (M3 Ultra)": "96 GB"
}

# Manual SKU overrides for Macs (real Apple SKUs from screenshot)
MANUAL_SKU_OVERRIDE = {
    # M4 Series (2024-2025) - Updated to match the image exactly
    "MacBook Air (2024, M4)": "Mac16,12 Mac16,13",
    "MacBook Pro (2024, M4)": "Mac16,1 Mac16,5 Mac16,6 Mac16,7 Mac16,8",
    "Mac mini (2024, M4)": "Mac16,10 Mac16,11",
    "iMac (2024, M4)": "Mac16,2 Mac16,3",
    
    # M3 Series (2023-2024) - Updated to match the image exactly
    "iMac (2023, M3)": "Mac15,4 Mac15,5",
    "MacBook Pro (2023, M3)": "Mac15,3 Mac15,6 Mac15,7 Mac15,8 Mac15,9",
    "MacBook Air (2024, M3)": "Mac15,12 Mac15,13",
    
    # M2 Series (2022-2023) - Updated to match the image exactly
    "MacBook Air (2022, M2)": "Mac14,2 Mac14,15",
    "MacBook Pro (2022, M2)": "Mac14,7 Mac14,5 Mac14,6 Mac14,9 Mac14,10",
    "Mac Mini (2023, M2)": "Mac14,3 Mac14,12",
    "Mac Pro (2023, M2)": "Mac14,8",
    "Mac Studio (2022, M2)": "Mac14,13 Mac14,14",
    
    # M1 Series (2020-2022) - Based on screenshot
    "MacBook Pro (2020, M1)": "MacBookPro17,1 MacBookPro18,1 MacBookPro19,1",
    "MacBook Air (2020, M1)": "MacBookAir10,1",
    "Mac Mini (2020, M1)": "Macmini9,1",
    "iMac (2021, M1)": "iMac21,1 iMac21,2",
    "Mac Studio (2022, M1)": "Mac13,1 Mac13,2",
    
    # Additional high-end models
    "Mac Studio (M4 Max)": "Mac16,9 Mac16,10",
    "Mac Studio (M3 Ultra)": "Mac15,17 Mac15,18"
}

def get_chip_from_board_config(target: str) -> str:
    """Get the chip name from the board config (target)."""
    if target in BOARD_CHIP_MAPPING:
        return BOARD_CHIP_MAPPING[target]
    
    for prefix, chip in BOARD_CHIP_MAPPING.items():
        if target.startswith(prefix):
            return chip
    
    return "Unknown"

def is_m1_or_newer(chip: str) -> bool:
    """Return True if chip is M1 or newer (M1, M1 Pro, M1 Max, M1 Ultra, M2, M3, M4, etc.)."""
    if not chip or chip == "Unknown":
        return False
    chip = chip.strip().upper()
    if chip.startswith("M"):
        return True
    return False

def find_xcode_databases() -> List[Tuple[str, str]]:
    """Find all available Xcode device_traits.db files."""
    databases = []
    # Check standard Xcode - Mac devices are in iPhoneOS platform
    standard_path = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"
    if os.path.exists(standard_path):
        databases.append(("Xcode", standard_path))
    
    # Check Xcode beta versions
    beta_paths = glob.glob("/Applications/Xcode-*.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db")
    for path in beta_paths:
        version = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))))
        databases.append((version, path))
    
    return sorted(databases, key=lambda x: x[0])

# --- Xcode device_traits.db ---
# Note: Mac devices are stored in the iPhoneOS platform database
DEFAULT_DB_PATH = "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/usr/standalone/device_traits.db"

def create_retry_session():
    """Create a requests session with retry logic."""
    session = requests.Session()
    retries = Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session

def fetch_wiki_text(session, device_type="Mac"):
    """Fetch Mac device data from Apple Wiki."""
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
    """Standardize RAM format."""
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
    """Extract chip information from wiki block."""
    chip_match = re.search(r'\*\s*CPU:\s*(?:\[\[(.*?)\]\]\s*)?\"?([\w\d\s\-+]+)\"?', block)
    if not chip_match:
        return "Unknown"
    chip = chip_match.group(2).strip()
    
    # Look for M-series chips first (M1, M1 Pro, M1 Max, M1 Ultra, M2, M3, M4, etc.)
    m_chip_match = re.search(r'\bM\d+(?:\s*(?:Pro|Max|Ultra))?\b', chip)
    if m_chip_match:
        return m_chip_match.group(0)
    
    return "Unknown"

def parse_wiki_devices(raw_text):
    """Parse Mac devices from wiki text."""
    entries = re.split(r"==\s*\[\[(.*?)\]\]\s*==", raw_text)
    data = {}
    for i in range(1, len(entries), 2):
        name = entries[i].strip()
        block = entries[i + 1]
        if name.startswith("File:"): 
            continue
        
        # Only include Mac models
        if not (re.search(r"Mac", name, re.IGNORECASE) or re.search(r"Mac", block, re.IGNORECASE)):
            continue
        
        chip = extract_chip(block)
        
        # Only include M1 and newer chips (M1, M1 Pro, M1 Max, M1 Ultra, M2, M2 Pro, M2 Max, M2 Ultra, M3, M3 Pro, M3 Max, M3 Ultra, M4, etc.)
        if not (chip.startswith("M") or chip == "Unknown"):
            continue
        
        ram_match = re.search(r"\*\s*RAM:\s*(.*?)\s*(?:\n|\r|$)", block, re.IGNORECASE)
        ram = ram_match.group(1).strip() if ram_match else "Unknown"
        ram = standardize_ram(ram)
        
        data[name] = {
            "chip": chip,
            "ram": ram
        }
    return data

def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> Optional[sqlite3.Connection]:
    """Get database connection."""
    if not os.path.exists(db_path):
        print(f"Warning: device_traits.db not found at {db_path}")
        return None
    try:
        return sqlite3.connect(db_path)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def get_xcode_version_from_db_path(db_path: str) -> str:
    """Extract Xcode version from database path."""
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

def generate_device_menu_json(db_path: str = DEFAULT_DB_PATH, ram_map: Dict[str, str] = None, chip_map: Dict[str, str] = None, xcode_version: str = "Xcode") -> Dict[str, Any]:
    """Generate Mac device menu JSON."""
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
                d.Platform
            FROM Devices d
            WHERE d.ProductType LIKE 'Mac%'
            ORDER BY d.ProductType DESC
        """)
        
        menu = {}
        unmatched_chips = []
        unmatched_ram = []
        
        for row in cursor.fetchall():
            model_name = row[0]
            sku = row[1]
            target = row[2]
            platform = row[3]
            
            # Get chip from manual override, wiki, or board config
            chip = MANUAL_CHIP_OVERRIDE.get(model_name)
            if not chip and chip_map:
                chip = chip_map.get(model_name)
                if not chip:
                    close = difflib.get_close_matches(model_name, chip_map.keys(), n=1, cutoff=0.8)
                    if close:
                        chip = chip_map[close[0]]
            
            if not chip:
                chip = get_chip_from_board_config(target)
                if chip == "Unknown":
                    unmatched_chips.append(model_name)
            
            # Get RAM from manual override, wiki, or default
            ram = MANUAL_RAM_OVERRIDE.get(model_name)
            if not ram and ram_map:
                ram = ram_map.get(model_name)
                if not ram:
                    close = difflib.get_close_matches(model_name, ram_map.keys(), n=1, cutoff=0.8)
                    if close:
                        ram = ram_map[close[0]]
            
            if not ram:
                # Default RAM for M1+ Macs based on chip type
                if chip and "Pro" in chip:
                    ram = "16 GB"
                elif chip and "Max" in chip:
                    ram = "32 GB"
                elif chip and "Ultra" in chip:
                    ram = "64 GB"
                else:
                    ram = "8 GB"  # Default for base M1/M2/M3/M4
                unmatched_ram.append(model_name)
            
            # Clean up SKU format
            sku = re.sub(r'-[A-Z]$', '', sku)
            
            # Only include M1 and newer Macs
            if not is_m1_or_newer(chip):
                continue
            
            menu[model_name] = {
                "sku": sku,
                "chip": chip,
                "ram": ram
            }
        
        if unmatched_chips:
            print("\nDevices with unmatched chip:")
            for name in unmatched_chips:
                print(f"  {name}")
        
        if unmatched_ram:
            print("\nDevices with unmatched RAM:")
            for name in unmatched_ram:
                print(f"  {name}")
        
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

def main():
    """Main function to generate Mac device specifications (M1 and newer only)."""
    os.makedirs("apple", exist_ok=True)
    
    # Find available Xcode databases
    available_dbs = find_xcode_databases()
    if not available_dbs:
        print("Error: No Xcode device_traits.db found!")
        return
    
    print("Available Xcode databases:")
    for i, (version, path) in enumerate(available_dbs, 1):
        print(f"{i}. {version} ({path})")
    
    # Use the beta version if available, otherwise use the latest
    selected_version, selected_path = next(
        ((v, p) for v, p in available_dbs if "Beta" in v or "Developer" in v),
        available_dbs[-1]
    )
    print(f"\nUsing {selected_version} database...")
    
    # Fetch Apple Wiki data for Macs
    print("Fetching Apple Wiki data for Mac...")
    try:
        session = create_retry_session()
        wiki_raw = fetch_wiki_text(session, device_type="Mac")
        wiki_devices = parse_wiki_devices(wiki_raw)
        
        ram_map = {name: meta["ram"] for name, meta in wiki_devices.items()}
        chip_map = {name: meta["chip"] for name, meta in wiki_devices.items()}
        
        print(f"Found {len(wiki_devices)} Mac models in Wiki data")
    except Exception as e:
        print(f"Warning: Could not fetch Wiki data: {e}")
        ram_map = {}
        chip_map = {}
    
    # Generate the device menu JSON
    print(f"Generating Mac device menu (from {selected_version})...")
    xcode_version_str = get_xcode_version_from_db_path(selected_path)
    menu_data = generate_device_menu_json(
        db_path=selected_path, 
        ram_map=ram_map, 
        chip_map=chip_map, 
        xcode_version=xcode_version_str
    )
    
    # If no devices found from database, use manual overrides to create comprehensive list
    if not menu_data["total_menu"]:
        print("No M1+ Macs found in database. Generating from manual overrides...")
        manual_menu = {}
        
        for model_name, chip in MANUAL_CHIP_OVERRIDE.items():
            ram = MANUAL_RAM_OVERRIDE.get(model_name, "8 GB")
            # Use real Apple SKUs from manual overrides and convert to list format
            sku_string = MANUAL_SKU_OVERRIDE.get(model_name, "Unknown")
            # Convert SKU string to list format (like iPad.json)
            if sku_string == "Unknown":
                sku = ["Unknown"]
            else:
                sku = sku_string.split()
            
            manual_menu[model_name] = {
                "sku": sku,
                "chip": chip,
                "ram": ram
            }
        
        menu_data["total_menu"] = manual_menu
        print(f"Generated {len(manual_menu)} Mac models from manual overrides")
    
    # Save to file
    with open("apple/Mac.json", "w") as f:
        json.dump(menu_data, f, indent=2)
    
    print(f"Done — Mac menu saved to apple/Mac.json (using {selected_version})")
    
    # Final count
    try:
        with open("apple/Mac.json", 'r') as f:
            data = json.load(f)
            count = len(data.get("total_menu", {}))
            print(f"\nTotal M1+ Mac models generated: {count}")
    except (FileNotFoundError, json.JSONDecodeError):
        print("\nCould not read file to count devices.")

if __name__ == "__main__":
    main() 