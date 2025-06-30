# Apple Device Knowledge Base

This project provides standalone scripts to generate a comprehensive JSON database of Apple device specifications (iPhone and iPad models) by combining data from public sources.

## Features

- Fetches device specs (chip, RAM, SKU) from TheAppleWiki and local Xcode resources
- Merges and standardizes the data into JSON files
- No dependencies on other scripts or files—just run the scripts you need

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
   ```

   This will create or update the respective JSON files in the `apple/` directory.

## Requirements

- Python 3.7+
- pandas
- requests

## Output

- `apple/iPhone.json`: Contains structured iPhone device data
- `apple/iPad.json`: Contains structured iPad device data

## Notes

- The scripts are fully standalone. You do not need any other files to generate the data.
- Each script focuses on a specific device type (iPhone or iPad).
- The data is filtered to include only recent devices:
  - iPhones: iPhone XR/XS and newer models
  - iPads: Models with A12 chip or newer

## Data Sources

- [The Apple Wiki](https://theapplewiki.com/) for device specifications
- Xcode (for device SKU information)

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

### iPad Data Format
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
│   └── iPad.json    # iPad specifications
└── src/
    ├── generate_apple_device_specs.py  # iPhone data generator
    └── generate_ipad_device_specs.py   # iPad data generator
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

- [The Apple Wiki](https://theapplewiki.com/) for device specifications
- Xcode for device SKU information 