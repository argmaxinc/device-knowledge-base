# Apple Device Knowledge Base

This project provides a standalone script to generate a comprehensive JSON database of Apple device specifications (currently iPhone models) by combining data from public sources.

## Features

- Fetches iPhone model specs (chip, RAM, SKU, release date) from Wikipedia, TheAppleWiki, and local Xcode resources
- Merges and standardizes the data into a single JSON file
- No dependencies on other scripts or files—just run one script

## Usage

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the script:**
   ```bash
   python generate_apple_device_specs.py
   ```

   This will create or update `apple/iPhone.json` with the latest device data.

## Requirements

- Python 3.7+
- pandas
- requests

## Output

- `apple/iPhone.json`: Contains structured iPhone device data.

## Notes

- The script is fully standalone. You do not need any other files to generate the data.
- To extend support for more device types (iPad, Mac, etc.), update the script accordingly.

## Data Sources

- [The Apple Wiki](https://theapplewiki.com/) for device specifications
- Wikipedia for release dates
- Xcode (for device SKU information)

## Data Format

```json
{
  "date_generated": "YYYY-MM-DD",
  "devices": {
    "device_name": {
      "sku": "device_sku",
      "chip": "chip_name",
      "ram": "X GB",
      "release_date": "YYYY-MM-DD"
    }
  }
}
```

## Repository Structure

```
.
├── README.md
├── generate_apple_device_specs.py
├── apple/
│   └── iPhone.json    # iPhone specifications
└── requirements.txt
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

[Add your license information here]

## Acknowledgments

- [The Apple Wiki](https://theapplewiki.com/) for device specifications
- Wikipedia for release dates
- Xcode for device SKU information (if available) 