# Apple Device Knowledge Base

This project provides standalone scripts to generate a comprehensive JSON database of Apple device specifications (iPhone, iPad, and Mac models) by combining data from public sources.

## Features

- Fetches device identifiers and chips from local Xcode resources and AppleDB, with RAM tables maintained in the scripts
- Merges and standardizes the data into JSON files
- No dependencies on other scripts or files—just run the scripts you need
- Uses the newest Xcode installed in `/Applications` (`Xcode.app` or any `Xcode-*.app`) so the device database is as current as possible

## Usage

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the scripts:**
   ```bash
   # For iPhone data
   python src/generate_apple_device_specs.py
   
   # For iPad data
   python src/generate_ipad_device_specs.py

   # For Mac data
   python src/generate_mac_device_specs.py
   ```

   This will create or update the respective JSON files in the `apple/` directory.

## Requirements

- Python 3.7+
- requests

## Output

- `apple/iPhone.json`: Contains structured iPhone device data
- `apple/iPad.json`: Contains structured iPad device data
- `apple/Mac.json`: Contains structured Mac device data

## Notes

- The scripts are fully standalone. You do not need any other files to generate the data.
- Each script focuses on a specific device type (iPhone, iPad, or Mac).
- The data is filtered to include only recent devices:
  - iPhones: iPhone XR/XS and newer models
  - iPads: Models with A12 chip or newer
  - Macs: Apple silicon models (M1 and newer, plus the A18 Pro MacBook Neo)
- Xcode's device database does not list Macs, so the Mac script is driven by the manual tables at the top of `src/generate_mac_device_specs.py`. Add new Macs there. The script checks every identifier and chip against AppleDB.
- RAM values are the base (entry) configuration for each model. Apple does not publish iPhone RAM, so the iPhone and iPad values are maintained as tables in the scripts.
- If AppleDB is unreachable the scripts fall back to the board config mappings in the scripts.

## Data Sources

- Xcode (for device SKU information)
- [AppleDB](https://appledb.dev/) (MIT licensed) for device names, chips, and identifier validation
- Apple tech specs pages for base memory where Apple publishes it

## Data Format

### iPhone Data Format
```json
{
  "date_generated": "YYYY-MM-DDTHH:MM:SS.SSSSSS",
  "xcode_version": "Version X.Y.Z (XXXXX)",
  "total_menu": {
    "device_name": {
      "sku": "device_sku",
      "chip": "chip_name",
      "ram": "X GB"
    }
  }
}
```

### iPad and Mac Data Format
```json
{
  "date_generated": "YYYY-MM-DDTHH:MM:SS.SSSSSS",
  "xcode_version": "Version X.Y.Z (XXXXX)",
  "total_menu": {
    "device_name": {
      "sku": ["sku1", "sku2"],  // List of SKUs for different variants
      "chip": "chip_name",
      "ram": "X GB"
    }
  }
}
```

## Repository Structure

```
.
├── README.md
├── LICENSE
├── requirements.txt
├── android/          # Future support for Android devices
├── apple/
│   ├── iPhone.json  # iPhone specifications
│   ├── iPad.json    # iPad specifications
│   └── Mac.json     # Mac specifications
└── src/
    ├── generate_apple_device_specs.py  # iPhone data generator
    ├── generate_ipad_device_specs.py   # iPad data generator
    └── generate_mac_device_specs.py    # Mac data generator
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [AppleDB](https://appledb.dev/) for device specifications
- Xcode for device SKU information 