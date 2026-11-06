"""Unit tests for Dr. Timezone's conversion and city-database helpers."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import main


class TimeConversionTests(unittest.TestCase):
    def test_conversion_can_cross_midnight(self):
        converted_date, hour, minute = main.convert_time(
            21,
            30,
            "America/New_York",
            "Europe/London",
            date(2026, 1, 15),
        )

        self.assertEqual(converted_date, date(2026, 1, 16))
        self.assertEqual((hour, minute), (2, 30))

    def test_conversion_uses_timezone_offset(self):
        converted_date, hour, minute = main.convert_time(
            12,
            30,
            "America/Toronto",
            "America/Vancouver",
            date(2026, 1, 15),
        )

        self.assertEqual(converted_date, date(2026, 1, 15))
        self.assertEqual((hour, minute), (9, 30))

    def test_valid_local_time_is_accepted(self):
        valid, message = main.validate_local_time(
            date(2026, 2, 10), 12, 30, "America/New_York"
        )

        self.assertTrue(valid)
        self.assertIsNone(message)

    def test_nonexistent_spring_forward_time_is_rejected(self):
        valid, message = main.validate_local_time(
            date(2026, 3, 8), 2, 30, "America/New_York"
        )

        self.assertFalse(valid)
        self.assertIn("does not exist", message)

    def test_ambiguous_fall_back_time_is_rejected(self):
        valid, message = main.validate_local_time(
            date(2026, 11, 1), 1, 30, "America/New_York"
        )

        self.assertFalse(valid)
        self.assertIn("occurs twice", message)

    def test_12_hour_formatting(self):
        cases = [
            (0, 5, "12:05 AM"),
            (11, 9, "11:09 AM"),
            (12, 0, "12:00 PM"),
            (13, 45, "01:45 PM"),
            (23, 59, "11:59 PM"),
        ]

        for hour, minute, expected in cases:
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(
                    main.convert_to_12_hour(hour, minute), expected
                )


class CityDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "cities.db"
        self.database_patch = patch.object(main, "CITY_DATABASE", self.database_path)
        self.database_patch.start()

        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """
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
            """
        )

        records = [
            (
                6182962, "Windsor", "Windsor", "Windsor City", "CA",
                "Canada", "Ontario", "America/Toronto", 229660,
            ),
            (
                5128581, "New York", "New York", "NYC, Big Apple", "US",
                "United States", "New York", "America/New_York", 8804190,
            ),
            (
                2988507, "Paris", "Paris", "", "FR", "France", "Île-de-France",
                "Europe/Paris", 2161000,
            ),
            (
                6094817, "Ottawa", "Ottawa", "", "CA", "Canada", "Ontario",
                "America/Toronto", 1017449,
            ),
            (
                1850147, "Tokyo", "Tokyo", "", "JP", "Japan", "Tokyo",
                "Asia/Tokyo", 13960000,
            ),
        ]
        connection.executemany(
            "INSERT INTO cities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", records
        )

        try:
            connection.execute(
                """
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
                """
            )
            connection.executemany(
                "INSERT INTO city_search VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (row[0], row[1], row[2], row[3], row[5], row[6], row[7])
                    for row in records
                ],
            )
        except sqlite3.OperationalError:
            # The production code deliberately supports SQLite builds without FTS5.
            pass

        connection.commit()
        connection.close()

    def tearDown(self):
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_lookup_returns_city_and_timezone(self):
        city = main.get_city_by_id("6182962")

        self.assertIsNotNone(city)
        self.assertEqual(city["city"], "Windsor")
        self.assertEqual(city["timezone"], "America/Toronto")
        self.assertEqual(city["label"], "Windsor, Ontario, Canada")

    def test_lookup_rejects_invalid_or_unknown_ids(self):
        self.assertIsNone(main.get_city_by_id("not-an-id"))
        self.assertIsNone(main.get_city_by_id("999999999"))

    def test_search_finds_city_by_name(self):
        results = main.search_cities("winds", limit=10)

        self.assertTrue(any(city["city"] == "Windsor" for city in results))

    def test_search_finds_city_by_alternate_name(self):
        results = main.search_cities("NYC", limit=10)

        self.assertTrue(any(city["city"] == "New York" for city in results))

    def test_random_suggestions_respect_requested_limit(self):
        results = main.get_random_cities(limit=4)

        self.assertEqual(len(results), 4)
        self.assertEqual(len({city["value"] for city in results}), 4)


if __name__ == "__main__":
    unittest.main()
