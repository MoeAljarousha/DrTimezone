"""Core timezone conversion and GeoNames city-catalogue functions."""

import csv
import io
import logging
import re
import shutil
import sqlite3
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# GeoNames provides a worldwide list of populated places, including each
# place's IANA timezone identifier. The database is cached locally so it is
# not downloaded on every application start.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CITY_DATABASE = DATA_DIR / "cities.db"
CITIES_ARCHIVE = DATA_DIR / "cities500.zip"
COUNTRIES_FILE = DATA_DIR / "countryInfo.txt"
ADMIN1_FILE = DATA_DIR / "admin1CodesASCII.txt"

GEONAMES_FILES = {
    CITIES_ARCHIVE: "https://download.geonames.org/export/dump/cities500.zip",
    COUNTRIES_FILE: "https://download.geonames.org/export/dump/countryInfo.txt",
    ADMIN1_FILE: "https://download.geonames.org/export/dump/admin1CodesASCII.txt",
}

# Refresh the cached catalogue approximately once a month.
DATA_REFRESH_DAYS = 30
_DOWNLOAD_TIMEOUT_SECONDS = 120
_DATABASE_LOCK = Lock()

logger = logging.getLogger(__name__)


def _download_file(url, destination, force=False):
    """Download a source file safely, keeping the old file if download fails."""
    if destination.exists() and not force:
        return

    temporary_path = destination.with_suffix(destination.suffix + ".download")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DrTimezone/1.0 (GeoNames city catalogue)"},
    )

    try:
        with urllib.request.urlopen(
            request, timeout=_DOWNLOAD_TIMEOUT_SECONDS
        ) as response, open(temporary_path, "wb") as output:
            shutil.copyfileobj(response, output)

        if temporary_path.stat().st_size == 0:
            raise RuntimeError(f"The downloaded file was empty: {destination.name}")

        temporary_path.replace(destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _read_country_names():
    """Return {ISO country code: country name} from GeoNames countryInfo.txt."""
    countries = {}

    with open(COUNTRIES_FILE, "r", encoding="utf-8") as source:
        for line in source:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 5:
                country_code = fields[0].strip()
                country_name = fields[4].strip()
                if country_code and country_name:
                    countries[country_code] = country_name

    return countries


def _read_admin1_names():
    """Return {country.admin1-code: administrative-area name}."""
    admin1_names = {}

    with open(ADMIN1_FILE, "r", encoding="utf-8") as source:
        for line in source:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 2 and fields[0].strip() and fields[1].strip():
                admin1_names[fields[0].strip()] = fields[1].strip()

    return admin1_names


def _build_city_database():
    """Build a searchable SQLite database from the GeoNames source files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_database = CITY_DATABASE.with_suffix(".building")

    if temporary_database.exists():
        temporary_database.unlink()

    country_names = _read_country_names()
    admin1_names = _read_admin1_names()
    inserted_count = 0
    batch = []
    search_batch = []

    connection = sqlite3.connect(temporary_database)
    fts_available = False

    try:
        connection.execute("""
            CREATE TABLE cities (
                geonameid INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                asciiname TEXT NOT NULL,
                alternatenames TEXT NOT NULL,
                country_code TEXT NOT NULL,
                country_name TEXT NOT NULL,
                admin1_name TEXT NOT NULL,
                timezone TEXT NOT NULL,
                population INTEGER NOT NULL
            )
        """)

        # FTS5 provides fast partial-word search across city names and aliases.
        # A LIKE-based search fallback is retained for Python builds without FTS5.
        try:
            connection.execute("""
                CREATE VIRTUAL TABLE city_search USING fts5(
                    geonameid UNINDEXED,
                    name,
                    asciiname,
                    alternatenames,
                    country_name,
                    admin1_name,
                    timezone,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
            fts_available = True
        except sqlite3.OperationalError:
            logger.warning("SQLite FTS5 is unavailable; using LIKE-based city search.")

        with zipfile.ZipFile(CITIES_ARCHIVE, "r") as archive:
            text_filename = next(
                (name for name in archive.namelist() if name.endswith(".txt")),
                None,
            )

            if text_filename is None:
                raise RuntimeError("The GeoNames archive did not contain a text file.")

            with archive.open(text_filename, "r") as raw_file:
                text_file = io.TextIOWrapper(raw_file, encoding="utf-8")
                reader = csv.reader(text_file, delimiter="\t")

                for fields in reader:
                    # GeoNames columns are documented in its export readme.
                    if len(fields) < 19 or fields[6] != "P":
                        continue

                    try:
                        geoname_id = int(fields[0])
                        population = int(fields[14] or 0)
                    except (ValueError, TypeError):
                        continue

                    name = fields[1].strip()
                    ascii_name = fields[2].strip()
                    alternate_names = fields[3].strip()
                    country_code = fields[8].strip()
                    admin1_code = fields[10].strip()
                    timezone_name = fields[17].strip()

                    if not name or not country_code or not timezone_name:
                        continue

                    # Ignore records whose timezone is not available to ZoneInfo.
                    try:
                        ZoneInfo(timezone_name)
                    except ZoneInfoNotFoundError:
                        continue

                    country_name = country_names.get(country_code, country_code)
                    admin1_key = f"{country_code}.{admin1_code}" if admin1_code else ""
                    admin1_name = admin1_names.get(admin1_key, "")

                    batch.append((
                        geoname_id,
                        name,
                        ascii_name or name,
                        alternate_names,
                        country_code,
                        country_name,
                        admin1_name,
                        timezone_name,
                        population,
                    ))

                    if fts_available:
                        search_batch.append((
                            geoname_id,
                            name,
                            ascii_name or name,
                            alternate_names,
                            country_name,
                            admin1_name,
                            timezone_name,
                        ))

                    if len(batch) >= 5000:
                        connection.executemany(
                            "INSERT OR REPLACE INTO cities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            batch,
                        )
                        if fts_available:
                            connection.executemany(
                                "INSERT INTO city_search VALUES (?, ?, ?, ?, ?, ?, ?)",
                                search_batch,
                            )
                            search_batch.clear()
                        inserted_count += len(batch)
                        batch.clear()

        if batch:
            connection.executemany(
                "INSERT OR REPLACE INTO cities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            if fts_available:
                connection.executemany(
                    "INSERT INTO city_search VALUES (?, ?, ?, ?, ?, ?, ?)",
                    search_batch,
                )
            inserted_count += len(batch)

        if inserted_count == 0:
            raise RuntimeError(
                "No usable city records were found in the GeoNames download."
            )

        connection.execute(
            "CREATE INDEX idx_cities_name ON cities(name COLLATE NOCASE)"
        )
        connection.execute(
            "CREATE INDEX idx_cities_ascii_name ON cities(asciiname COLLATE NOCASE)"
        )
        connection.execute(
            "CREATE INDEX idx_cities_country ON cities(country_name COLLATE NOCASE)"
        )
        connection.commit()

    finally:
        connection.close()

    temporary_database.replace(CITY_DATABASE)
    logger.info("Loaded %s populated places from GeoNames.", inserted_count)


def ensure_city_database():
    """Make sure the local GeoNames database exists and is reasonably current."""
    with _DATABASE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        database_is_fresh = False
        if CITY_DATABASE.exists():
            age_seconds = datetime.now().timestamp() - CITY_DATABASE.stat().st_mtime
            database_is_fresh = age_seconds < DATA_REFRESH_DAYS * 24 * 60 * 60

        if database_is_fresh:
            return

        try:
            for destination, url in GEONAMES_FILES.items():
                _download_file(url, destination, force=True)

            _build_city_database()

        except Exception:
            # An existing database is better than taking the app offline when
            # GeoNames is temporarily unreachable during a refresh.
            if CITY_DATABASE.exists():
                logger.exception(
                    "Could not refresh GeoNames. Continuing with the cached city database."
                )
                return
            raise


def _city_record_to_dict(row):
    """Convert one SQLite row into the structure used by Flask and Tom Select."""
    city_name = row["name"]
    region = row["admin1_name"]
    country = row["country_name"] or row["country_code"]

    label_parts = [city_name]
    if region:
        label_parts.append(region)
    if country:
        label_parts.append(country)

    return {
        "geonameid": row["geonameid"],
        "value": str(row["geonameid"]),
        "city": city_name,
        "region": region,
        "country": country,
        "label": ", ".join(label_parts),
        "text": ", ".join(label_parts),
        "timezone": row["timezone"],
        "population": row["population"],
    }


def get_random_cities(limit=4):
    """Return a small random sample of places for the empty search dropdown."""
    if not CITY_DATABASE.exists():
        return []

    safe_limit = max(1, min(int(limit), 10))
    connection = sqlite3.connect(CITY_DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute("""
            SELECT geonameid, name, country_code, country_name,
                   admin1_name, timezone, population
            FROM cities
            ORDER BY RANDOM()
            LIMIT ?
        """, (safe_limit,)).fetchall()

        return [_city_record_to_dict(row) for row in rows]

    finally:
        connection.close()


def search_cities(query, limit=50):
    """Search the local catalogue and return the best matching populated places."""
    query = " ".join((query or "").split())[:80]
    if len(query) < 2 or not CITY_DATABASE.exists():
        return []

    connection = sqlite3.connect(CITY_DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row

    try:
        has_fts = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'city_search'"
        ).fetchone()

        if has_fts:
            # Treat each word as a prefix token. This supports searches such as
            # "York" -> New York and ignores accents in names where possible.
            tokens = re.findall(r"\w+", query, flags=re.UNICODE)
            if not tokens:
                return []
            fts_query = " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)

            rows = connection.execute("""
                SELECT cities.geonameid, cities.name, cities.country_code,
                       cities.country_name, cities.admin1_name,
                       cities.timezone, cities.population
                FROM city_search
                JOIN cities
                  ON cities.geonameid = CAST(city_search.geonameid AS INTEGER)
                WHERE city_search MATCH ?
                ORDER BY
                    CASE
                        WHEN cities.name = ? COLLATE NOCASE THEN 0
                        WHEN cities.asciiname = ? COLLATE NOCASE THEN 1
                        WHEN cities.name LIKE ? COLLATE NOCASE THEN 2
                        WHEN cities.asciiname LIKE ? COLLATE NOCASE THEN 3
                        ELSE 4
                    END,
                    cities.population DESC,
                    cities.name COLLATE NOCASE ASC
                LIMIT ?
            """, (
                fts_query,
                query,
                query,
                f"{query}%",
                f"{query}%",
                max(1, min(int(limit), 100)),
            )).fetchall()
        else:
            # Portable fallback for SQLite builds without FTS5.
            escaped_query = (
                query.replace("!", "!!")
                .replace("%", "!%")
                .replace("_", "!_")
            )
            contains = f"%{escaped_query}%"
            starts_with = f"{escaped_query}%"

            rows = connection.execute("""
                SELECT geonameid, name, country_code, country_name,
                       admin1_name, timezone, population
                FROM cities
                WHERE name LIKE ? ESCAPE '!' COLLATE NOCASE
                   OR asciiname LIKE ? ESCAPE '!' COLLATE NOCASE
                   OR alternatenames LIKE ? ESCAPE '!' COLLATE NOCASE
                   OR country_name LIKE ? ESCAPE '!' COLLATE NOCASE
                   OR admin1_name LIKE ? ESCAPE '!' COLLATE NOCASE
                   OR timezone LIKE ? ESCAPE '!' COLLATE NOCASE
                ORDER BY
                    CASE
                        WHEN name = ? COLLATE NOCASE THEN 0
                        WHEN asciiname = ? COLLATE NOCASE THEN 1
                        WHEN name LIKE ? ESCAPE '!' COLLATE NOCASE THEN 2
                        WHEN asciiname LIKE ? ESCAPE '!' COLLATE NOCASE THEN 3
                        ELSE 4
                    END,
                    population DESC,
                    name COLLATE NOCASE ASC
                LIMIT ?
            """, (
                contains, contains, contains, contains, contains, contains,
                query, query, starts_with, starts_with,
                max(1, min(int(limit), 100)),
            )).fetchall()

        return [_city_record_to_dict(row) for row in rows]

    finally:
        connection.close()


def get_city_by_id(city_id):
    """Look up a city using the GeoNames ID submitted by the browser."""
    try:
        geoname_id = int(city_id)
    except (TypeError, ValueError):
        return None

    if not CITY_DATABASE.exists():
        return None

    connection = sqlite3.connect(CITY_DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row

    try:
        row = connection.execute("""
            SELECT geonameid, name, country_code, country_name,
                   admin1_name, timezone, population
            FROM cities
            WHERE geonameid = ?
        """, (geoname_id,)).fetchone()

        return _city_record_to_dict(row) if row else None

    finally:
        connection.close()


def validate_local_time(selected_date, hours, minutes, timezone_name):
    """Reject nonexistent and ambiguous local times around DST transitions."""
    naive_time = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        hours,
        minutes,
    )

    timezone = ZoneInfo(timezone_name)
    time_fold_0 = naive_time.replace(tzinfo=timezone, fold=0)
    time_fold_1 = naive_time.replace(tzinfo=timezone, fold=1)

    valid_0 = (
        time_fold_0.astimezone(ZoneInfo("UTC"))
        .astimezone(timezone)
        .replace(tzinfo=None) == naive_time
    )
    valid_1 = (
        time_fold_1.astimezone(ZoneInfo("UTC"))
        .astimezone(timezone)
        .replace(tzinfo=None) == naive_time
    )

    if not valid_0 and not valid_1:
        return False, "This local time does not exist because of daylight saving time."

    if valid_0 and valid_1 and time_fold_0.utcoffset() != time_fold_1.utcoffset():
        return False, "This local time occurs twice because of daylight saving time."

    return True, None


def convert_time(hours, minutes, old_timezone, new_timezone, selected_date):
    """Convert a local time and return the destination date, hour, and minute."""
    old_time = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        hours,
        minutes,
        tzinfo=ZoneInfo(old_timezone),
    )

    new_time = old_time.astimezone(ZoneInfo(new_timezone))
    return new_time.date(), new_time.hour, new_time.minute


def convert_to_12_hour(hour, minute):
    """Format a 24-hour time as a 12-hour clock string."""
    display_hour = hour % 12 or 12
    suffix = "AM" if hour < 12 else "PM"
    return f"{display_hour:02d}:{minute:02d} {suffix}"
