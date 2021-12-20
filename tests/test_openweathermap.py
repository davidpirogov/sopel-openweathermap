import unittest

from sopel_openweathermap import utils


class TestInputLocationParsingMethods(unittest.TestCase):
    """
    https://docs.python.org/3.8/library/unittest.html#basic-example
    """

    def test_geocoordinate_latitude_out_of_bounds(self):
        # Test Latitude out of bounds and Longitude in bounds
        self.assertEqual(self.generate_is_geocoordinate_expression("91.12345", "145.12345", ";"), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("-91.12345", "145.12345", ";"), False)

        self.assertEqual(self.generate_is_geocoordinate_expression("91.12345", "145.12345", ","), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("-91.12345", "145.12345", ","), False)


    def test_geocoordinate_longitude_out_of_bounds(self):
        # Test Latitude in bounds and Longitude out of bounds
        self.assertEqual(self.generate_is_geocoordinate_expression("41.12345", "181.12345", ";"), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("-41.12345", "-181.12345", ";"), False)

        self.assertEqual(self.generate_is_geocoordinate_expression("41.12345", "181.12345", ","), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("-41.12345", "-181.12345", ","), False)


    def test_geocoordinate_square_bracket_values(self):
        # Tests for values that should be permitted
        self.assertEqual(self.generate_is_geocoordinate_expression_brackets("40.445","-95.235",";"), True)
        self.assertEqual(self.generate_is_geocoordinate_expression_brackets("35.329","-93.253",";"), True)
        self.assertEqual(self.generate_is_geocoordinate_expression_brackets("36.4761","-119.4432",","), True)
        self.assertEqual(self.generate_is_geocoordinate_expression_brackets("-36.4761","119.4432",","), True)


    def test_geocoordinate_invalid_values(self):
        # Tests for values that should not be permitted
        self.assertEqual(self.generate_is_geocoordinate_expression("", "", ";"), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("", "", ","), False)

        self.assertEqual(self.generate_is_geocoordinate_expression("asdf", "asdf", ";"), False)
        self.assertEqual(self.generate_is_geocoordinate_expression("asdf", "asdf", ","), False)


    def generate_is_geocoordinate_expression(self, latitude:str, longitude:str, separator:str) -> bool:
        """
        Combines the latitude, longitude, and separator into an is_geolocation check
        """
        return utils.is_geolocation(f"{latitude}{separator}{longitude}", separator)


    def generate_is_geocoordinate_expression_brackets(self, latitude:str, longitude:str, separator:str) -> bool:
        """
        Combines the latitude, longitude, and separator into an is_geolocation check with square brackets
        """
        return utils.is_geolocation(f"[{latitude}{separator}{longitude}]", separator)


    def test_place_ids(self):

        # Test the variations of place id's that are allowed
        self.assertEqual(utils.is_place_id("A"), False)
        self.assertEqual(utils.is_place_id("#"), False)
        self.assertEqual(utils.is_place_id(""), False)
        self.assertEqual(utils.is_place_id("1"), True)
        self.assertEqual(utils.is_place_id("100000000000000"), True)
        self.assertEqual(utils.is_place_id("#1"), True)
        self.assertEqual(utils.is_place_id("#10000000"), True)
        self.assertEqual(utils.is_place_id("#-123546"), False)
        self.assertEqual(utils.is_place_id("-423546"), False)


    def test_location_query_city(self):
        valid_city = {"city": "melbourne"}

        self.assertEqual(utils.get_location_string("melbourne"), valid_city)
        self.assertEqual(utils.get_location_string("   melbourne   "), valid_city)


    def test_location_query_city_country(self):

        valid_city_country = {"city": "melbourne", "country": "AU"}
        self.assertEqual(utils.get_location_string("melbourne,au"), valid_city_country)
        self.assertEqual(utils.get_location_string("   melbourne,au    "), valid_city_country)
        self.assertEqual(utils.get_location_string("  melbourne, au"), valid_city_country)
        self.assertEqual(utils.get_location_string("  melbourne, au   "), valid_city_country)


    # Functionality disabled until OpenWeatherMap API supports state/country
    # def test_location_query_city_state_country(self):
    #
    #     valid_city_state_country = {"city": "melbourne", "state": "OH", "country": "US"}
    #     self.assertEqual(utils.get_location_string("melbourne,oh,us"), valid_city_state_country)
    #     self.assertEqual(utils.get_location_string("  melbourne,oh,us  "), valid_city_state_country)
    #     self.assertEqual(utils.get_location_string("melbourne, oh, us"), valid_city_state_country)
    #     self.assertEqual(utils.get_location_string("melbourne, oh , us  "), valid_city_state_country)


    def test_location_invalid_values(self):

        self.assertEqual(utils.get_location_string(""), {"city": ""})
        self.assertEqual(utils.get_location_string(","), {"city": "", "country": ""})
        self.assertEqual(utils.get_location_string(",,"), None)
        self.assertEqual(utils.get_location_string(",,,"), None)
        self.assertEqual(utils.get_location_string(",,,,"), None)


    def test_construct_location_name(self):

        self.assertEqual(utils.construct_location_name({'type': 'location', 'city': 'london'}), "london")
        self.assertEqual(utils.construct_location_name({'type': 'location', 'city': 'london', 'country': 'CA'}), "london,CA")
        self.assertEqual(utils.construct_location_name({'type': 'geocoords', 'latitude': 37.129, 'longitude': -84.0833}), "37.129,-84.0833")
        self.assertEqual(utils.construct_location_name({'type': 'place_id', 'place_id':123456}), "123456")


    def test_field_sanitization(self):

        self.assertEqual(utils.sanitize_field("12345"), "")
        self.assertEqual(utils.sanitize_field("abcdef"), "abcdef")
        self.assertEqual(utils.sanitize_field("ABCDEF"), "ABCDEF")
        self.assertEqual(utils.sanitize_field(" ABCDEF "), "ABCDEF")
        self.assertEqual(utils.sanitize_field("A1B2C3D4E5F6"), "ABCDEF")
        self.assertEqual(utils.sanitize_field("A@#$%^&B"), "AB")


    def test_field_sanitization_unicode_multilingual(self):

        self.assertEqual(utils.sanitize_field("fjörður"), "fjörður")
        self.assertEqual(utils.sanitize_field("село "), "село")
        self.assertEqual(utils.sanitize_field("ビレッジ"), "ビレッジ")


    def test_field_sanitization_exact_token(self):

        self.assertEqual(utils.sanitize_field("!fjörð"), "!fjörð")
        self.assertEqual(utils.sanitize_field("   !fjörð"), "!fjörð")
        self.assertEqual(utils.sanitize_field("ABC!DEF"), "ABCDEF")


    def test_field_sanitization_like_token(self):

        self.assertEqual(utils.sanitize_field("*fjörð"), "*fjörð")
        self.assertEqual(utils.sanitize_field("   *fjörð"), "*fjörð")
        self.assertEqual(utils.sanitize_field("ABC*DEF"), "ABCDEF")


    def test_field_sanitization_spaces_in_names(self):

        self.assertEqual(utils.sanitize_field("mestská štvrť"), "mestská štvrť")
        self.assertEqual(utils.sanitize_field("pražskom hrade"), "pražskom hrade")
        self.assertEqual(utils.sanitize_field("Los Angeles"), "Los Angeles")





if __name__ == '__main__':
    unittest.main()
