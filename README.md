# Dr. Timezone

Dr. Timezone is a web-based timezone converter built with Python and Flask. It lets users search for cities around the world, select a source and destination, and convert a local date and time between their IANA timezones.

The project uses GeoNames to build a local SQLite catalogue of populated places. Python's `zoneinfo` module performs the actual timezone conversion, including daylight-saving-time rules.

## Features

- Searchable city selectors backed by a local SQLite database.
- Four random city suggestions when a city selector is opened.
- City results include available administrative-region and country information to help distinguish places with the same name.
- Time conversion using IANA timezone identifiers and Python's `zoneinfo` module.
- Detection of local times that do not exist during a daylight-saving-time transition.
- Detection of local times that occur twice during a daylight-saving-time transition.
- Correct destination dates when a conversion crosses midnight.
- A responsive interface built with HTML, CSS, and JavaScript.

## Technology

- **Python** — timezone conversion, validation, and data processing.
- **Flask** — web application and city-search API.
- **SQLite** — local city catalogue and search index.
- **GeoNames** — worldwide geographical-name data.
- **IANA Time Zone Database** — timezone identifiers and transition rules, accessed through Python's `zoneinfo` module.
- **Tom Select** — searchable city selectors.
- **HTML, CSS, and JavaScript** — browser interface and interactions.

## City data and coverage

On its first run, the application downloads the GeoNames `cities500` extract, along with country and first-level administrative-area names, then builds a local SQLite database in the `data/` directory.

GeoNames describes `cities500` as containing approximately 185,000 places: places with a population greater than 500 and certain administrative seats. This is a large global populated-place catalogue, but it is not a list of every settlement or every locality in the world. Coverage and place-name accuracy depend on the upstream GeoNames data.

The city database is generated locally and is not committed to this repository. The application checks the database age on startup and attempts to refresh it approximately every 30 days. An existing database is retained if a refresh fails.

### GeoNames attribution

This project uses geographical data from [GeoNames](https://www.geonames.org/), licensed under the [Creative Commons Attribution 4.0 License](https://creativecommons.org/licenses/by/4.0/). GeoNames provides its data as-is and does not warrant its accuracy, timeliness, or completeness. This project is not affiliated with or endorsed by GeoNames.

## Project structure

```text
DrTimezone/
├── app.py                  # Flask application and HTTP routes
├── main.py                 # GeoNames import, SQLite search, and timezone logic
├── requirements.txt        # Runtime Python dependencies
├── README.md
├── .gitignore
├── templates/
│   └── index.html          # Jinja/HTML interface
├── static/
│   ├── styles.css          # Application styling
│   └── clock.js            # Current-time and date helpers
└── tests/
    └── test_timezone.py    # Automated tests
```

The `data/` directory is created automatically when the application initializes the city catalogue.

## Run locally

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd DrTimezone
```

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

The `tzdata` dependency provides IANA timezone data on systems, such as many Windows installations, that do not include a system timezone database.

### 4. Start the application

```bash
python app.py
```

Open the local address printed by Flask, normally `http://127.0.0.1:5000`.

**First-run note:** An internet connection is required the first time the application builds the city catalogue. The GeoNames files are downloaded and imported into `data/cities.db`. Subsequent starts use the local database unless it is due for its periodic refresh. If the initial download fails, check your connection and restart the application.

## Run tests

The test suite uses Python's standard-library `unittest` framework and does not download the GeoNames dataset.

```bash
python -m unittest discover -s tests -v
```

The tests cover:

- Conversion across timezone offsets and midnight.
- Valid local times.
- Nonexistent and ambiguous local times around daylight-saving transitions.
- 12-hour clock formatting.
- City lookup, search, and random suggestions using a temporary SQLite database.

## How the application works

1. The browser requests the Flask page.
2. When a city selector receives focus, Tom Select requests a small set of random city suggestions from `/api/cities`.
3. When the user types at least two characters, the same endpoint searches the local SQLite catalogue and returns matching places.
4. The selected GeoNames IDs are submitted to Flask. The server looks up each place and obtains its IANA timezone identifier.
5. The application validates the source local time for daylight-saving-time gaps and folds.
6. `zoneinfo` converts the source datetime to the destination timezone and returns the converted date and time.

SQLite uses FTS5 full-text search when the installed SQLite build supports it, with a `LIKE`-based fallback for builds without FTS5.

## Known limitations

- Search results are limited to places in the GeoNames `cities500` extract; smaller settlements may not be present.
- Place names, alternate names, administrative labels, and population values come from GeoNames and may contain omissions or inconsistencies.
- The project currently focuses on converting a user-entered date and time. It is not a calendar scheduler or meeting-planning service.
- The included Flask development server is intended for local development. Use a production WSGI server and disable debug mode before deploying publicly.

## License

The application source code in this repository is provided under the MIT License. The GeoNames dataset is separate third-party data licensed under CC BY 4.0; see the attribution above. Add a `LICENSE` file before publishing if you intend to distribute the source code under MIT, and confirm that this is the license you want to use.
