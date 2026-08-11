"""
Tests for PersonalityEngine deduplication and trait handling.
"""

import unittest
from unittest.mock import Mock, patch
import json
import tempfile
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from asomien.personality.engine import PersonalityEngine


class TestPersonalityEngine(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a temporary personality seed file for testing
        self.test_seed_data = {
            "persona_name": "test_persona",
            "persona_tagline": "a test persona",
            "voice_description": "test voice",
            "writing_rules": {
                "case": "lowercase_always",
                "punctuation": "natural",
                "emoji_policy": "zero",
                "sentence_length": "short",
                "forbidden_openers": ["I "],
                "forbidden_phrases": ["hustle"],
                "voice_notes": ["test note"]
            },
            "core_traits": [
                {
                    "trait_name": "relatability_score",
                    "trait_type": "core",
                    "value": 0.95,
                    "description": "Test relatability"
                },
                {
                    "trait_name": "advice_aversion",
                    "trait_type": "core",
                    "value": 1.00,
                    "description": "Test advice aversion"
                },
                # Intentional duplicate for testing
                {
                    "trait_name": "relatability_score",
                    "trait_type": "core",
                    "value": 0.80,  # Different value
                    "description": "Duplicate relatability"
                }
            ],
            "adaptive_traits": [
                {
                    "trait_name": "ai_bit_frequency",
                    "trait_type": "adaptive",
                    "value": 0.20,
                    "description": "Test AI bit frequency"
                },
                # Intentional duplicate for testing
                {
                    "trait_name": "ai_bit_frequency",
                    "trait_type": "adaptive",
                    "value": 0.30,  # Different value
                    "description": "Duplicate AI bit frequency"
                }
            ],
            "example_approved_posts": [
                "this is an approved test post"
            ],
            "example_rejected_posts": [
                "this is a rejected test post"
            ]
        }

        # Create temporary file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.test_seed_data, self.temp_file)
        self.temp_file.close()

    def tearDown(self):
        """Clean up after each test method."""
        os.unlink(self.temp_file.name)

    def test_deduplication_removes_duplicate_core_traits(self):
        """Test that _deduplicate_traits removes duplicate core traits."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)

        # Should have deduplicated core traits (only 2 unique instead of 3)
        core_traits = engine.core_traits
        self.assertEqual(len(core_traits), 2)

        # Should keep the first occurrence of each trait
        trait_names = [trait["trait_name"] for trait in core_traits]
        self.assertIn("relatability_score", trait_names)
        self.assertIn("advice_aversion", trait_names)

        # Should have kept the first relatability_score (value 0.95, not 0.80)
        relatability_trait = next(t for t in core_traits if t["trait_name"] == "relatability_score")
        self.assertEqual(relatability_trait["value"], 0.95)

    def test_deduplication_removes_duplicate_adaptive_traits(self):
        """Test that _deduplicate_traits removes duplicate adaptive traits."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)

        # Should have deduplicated adaptive traits (only 1 unique instead of 2)
        adaptive_traits = engine.adaptive_traits
        self.assertEqual(len(adaptive_traits), 1)

        # Should keep the first occurrence
        self.assertEqual(adaptive_traits[0]["trait_name"], "ai_bit_frequency")
        self.assertEqual(adaptive_traits[0]["value"], 0.20)  # First value, not 0.30

    def test_get_trait_value_returns_first_occurrence(self):
        """Test that get_trait_value returns the value from the first occurrence."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)

        # Should return the first relatability_score value (0.95), not the duplicate (0.80)
        relatability_value = engine._get_trait_value("relatability_score")
        self.assertEqual(relatability_value, 0.95)

        # Should return the first ai_bit_frequency value (0.20), not the duplicate (0.30)
        ai_bit_value = engine._get_trait_value("ai_bit_frequency")
        self.assertEqual(ai_bit_value, 0.20)

    def test_get_trait_returns_first_occurrence(self):
        """Test that get_trait returns the first occurrence of a trait."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)

        relatability_trait = engine.get_trait("relatability_score")
        self.assertIsNotNone(relatability_trait)
        self.assertEqual(relatability_trait["value"], 0.95)
        self.assertEqual(relatability_trait["description"], "Test relatability")

    def test_no_duplicates_when_seed_has_none(self):
        """Test that deduplication works correctly when there are no duplicates."""
        # Create seed data without duplicates
        no_dup_seed = {
            "persona_name": "test_persona",
            "persona_tagline": "a test persona",
            "voice_description": "test voice",
            "writing_rules": {
                "case": "lowercase_always",
                "punctuation": "natural",
                "emoji_policy": "zero",
                "sentence_length": "short",
                "forbidden_openers": ["I "],
                "forbidden_phrases": ["hustle"],
                "voice_notes": ["test note"]
            },
            "core_traits": [
                {
                    "trait_name": "relatability_score",
                    "trait_type": "core",
                    "value": 0.95,
                    "description": "Test relatability"
                },
                {
                    "trait_name": "advice_aversion",
                    "trait_type": "core",
                    "value": 1.00,
                    "description": "Test advice aversion"
                }
            ],
            "adaptive_traits": [
                {
                    "trait_name": "ai_bit_frequency",
                    "trait_type": "adaptive",
                    "value": 0.20,
                    "description": "Test AI bit frequency"
                }
            ],
            "example_approved_posts": ["test approved"],
            "example_rejected_posts": ["test rejected"]
        }

        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(no_dup_seed, temp_file)
        temp_file.close()

        try:
            engine = PersonalityEngine(seed_path=temp_file.name)

            # Should have all traits since there were no duplicates
            self.assertEqual(len(engine.core_traits), 2)
            self.assertEqual(len(engine.adaptive_traits), 1)

            # Values should be correct
            self.assertEqual(engine._get_trait_value("relatability_score"), 0.95)
            self.assertEqual(engine._get_trait_value("advice_aversion"), 1.00)
            self.assertEqual(engine._get_trait_value("ai_bit_frequency"), 0.20)
        finally:
            os.unlink(temp_file.name)

    def test_apply_to_prompt_includes_deduplicated_traits(self):
        """Test that apply_to_prompt includes deduplicated traits in the output."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        prompt = engine.apply_to_prompt("generate a test post")

        # Should contain the trait values (first occurrences)
        self.assertIn("**relatability_score** = 0.95", prompt)
        self.assertIn("**advice_aversion** = 1.0", prompt)
        self.assertIn("**ai_bit_frequency** = 0.2", prompt)

        # Should not contain the duplicate values
        self.assertNotIn("**relatability_score** = 0.8", prompt)
        self.assertNotIn("**ai_bit_frequency** = 0.3", prompt)

    def test_is_trait_duplicate_by_name(self):
        """Test that _is_trait_duplicate correctly identifies duplicates by trait_name."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)

        # Test exact match (case insensitive)
        new_trait = {
            "trait_name": "RELATABILITY_SCORE",  # uppercase
            "trait_type": "core",
            "value": 0.5,
            "description": "Different description"
        }
        is_dup = engine._is_trait_duplicate(new_trait, engine.core_traits)
        self.assertTrue(is_dup)

        # Test with different case and spaces
        new_trait2 = {
            "trait_name": "  relatability_score  ",
            "trait_type": "core",
            "value": 0.5,
            "description": "Another description"
        }
        is_dup2 = engine._is_trait_duplicate(new_trait2, engine.core_traits)
        self.assertTrue(is_dup2)

        # Test non-duplicate by name
        new_trait3 = {
            "trait_name": "new_trait",
            "trait_type": "core",
            "value": 0.5,
            "description": "New trait description"
        }
        is_dup3 = engine._is_trait_duplicate(new_trait3, engine.core_traits)
        self.assertFalse(is_dup3)

    def test_is_trait_duplicate_by_description(self):
        """Test that _is_trait_duplicate correctly identifies duplicates by description similarity."""
        # Create a temporary engine without existing traits to test description similarity
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        no_trait_seed = {
            "persona_name": "test_persona",
            "persona_tagline": "a test persona",
            "voice_description": "test voice",
            "writing_rules": {
                "case": "lowercase_always",
                "punctuation": "natural",
                "emoji_policy": "zero",
                "sentence_length": "short",
                "forbidden_openers": ["I "],
                "forbidden_phrases": ["hustle"],
                "voice_notes": ["test note"]
            },
            "core_traits": [],  # Empty to test description similarity in isolation
            "adaptive_traits": [],
            "example_approved_posts": ["test approved"],
            "example_rejected_posts": ["test rejected"]
        }
        json.dump(no_trait_seed, temp_file)
        temp_file.close()

        try:
            engine = PersonalityEngine(seed_path=temp_file.name)

            # Test similar descriptions
            trait1 = {
                "trait_name": "trait_one",
                "trait_type": "core",
                "value": 0.5,
                "description": "This is a test description for similarity testing"
            }
            trait2 = {
                "trait_name": "trait_two",  # different name
                "trait_type": "core",
                "value": 0.6,
                "description": "This is a test description for similarity testing"  # same description
            }

            # First trait should not be duplicate (empty list)
            is_dup1 = engine._is_trait_duplicate(trait1, [])
            self.assertFalse(is_dup1)

            # Add first trait to existing traits
            existing_traits = [trait1]

            # Second trait should be duplicate (similar description)
            is_dup2 = engine._is_trait_duplicate(trait2, existing_traits)
            self.assertTrue(is_dup2)

            # Test dissimilar descriptions
            trait3 = {
                "trait_name": "trait_three",
                "trait_type": "core",
                "value": 0.7,
                "description": "Completely different description about something else"
            }
            is_dup3 = engine._is_trait_duplicate(trait3, existing_traits)
            self.assertFalse(is_dup3)
        finally:
            os.unlink(temp_file.name)

    def test_add_trait_non_duplicate_core(self):
        """Test adding a non-duplicate core trait increases the trait list."""
        # Use the existing seed file which has core traits
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_core_count = len(engine.core_traits)

        # Define a new core trait that is not a duplicate
        new_trait = {
            "trait_name": "new_core_trait",
            "trait_type": "core",
            "value": 0.5,
            "description": "A new core trait for testing"
        }

        # Add the trait
        result = engine.add_trait(new_trait)
        self.assertTrue(result, "Expected add_trait to return True for non-duplicate trait")
        self.assertEqual(len(engine.core_traits), initial_core_count + 1,
                         "Expected core traits count to increase by 1")

        # Verify the trait was added and can be retrieved
        added_trait = engine.get_trait("new_core_trait")
        self.assertIsNotNone(added_trait)
        self.assertEqual(added_trait["trait_name"], "new_core_trait")
        self.assertEqual(added_trait["value"], 0.5)
        self.assertEqual(added_trait["description"], "A new core trait for testing")

    def test_add_trait_duplicate_core_by_name(self):
        """Test adding a duplicate core trait by name does not increase the trait list."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_core_count = len(engine.core_traits)

        # Define a trait that duplicates an existing core trait by name (case insensitive)
        new_trait = {
            "trait_name": "RELATABILITY_SCORE",  # uppercase of an existing trait
            "trait_type": "core",
            "value": 0.5,
            "description": "A duplicate trait by name"
        }

        # Add the trait
        result = engine.add_trait(new_trait)
        self.assertFalse(result, "Expected add_trait to return False for duplicate trait by name")
        self.assertEqual(len(engine.core_traits), initial_core_count,
                         "Expected core traits count to remain the same")

    def test_add_trait_duplicate_core_by_description(self):
        """Test adding a core trait with similar description does not increase the trait list."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_core_count = len(engine.core_traits)

        # Find an existing core trait to use for description similarity
        if engine.core_traits:
            existing_trait = engine.core_traits[0]
            # Create a new trait with a different name but very similar description
            new_trait = {
                "trait_name": "new_trait_with_similar_desc",
                "trait_type": "core",
                "value": 0.5,
                "description": existing_trait["description"]  # Same description
            }

            # Add the trait
            result = engine.add_trait(new_trait)
            self.assertFalse(result, "Expected add_trait to return False for duplicate trait by description")
            self.assertEqual(len(engine.core_traits), initial_core_count,
                             "Expected core traits count to remain the same")
        else:
            self.skipTest("No core traits available to test description similarity")

    def test_add_trait_non_duplicate_adaptive(self):
        """Test adding a non-duplicate adaptive trait increases the trait list."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_adaptive_count = len(engine.adaptive_traits)

        # Define a new adaptive trait that is not a duplicate
        new_trait = {
            "trait_name": "new_adaptive_trait",
            "trait_type": "adaptive",
            "value": 0.5,
            "description": "A new adaptive trait for testing"
        }

        # Add the trait
        result = engine.add_trait(new_trait)
        self.assertTrue(result, "Expected add_trait to return True for non-duplicate trait")
        self.assertEqual(len(engine.adaptive_traits), initial_adaptive_count + 1,
                         "Expected adaptive traits count to increase by 1")

        # Verify the trait was added and can be retrieved
        added_trait = engine.get_trait("new_adaptive_trait")
        self.assertIsNotNone(added_trait)
        self.assertEqual(added_trait["trait_name"], "new_adaptive_trait")
        self.assertEqual(added_trait["value"], 0.5)
        self.assertEqual(added_trait["description"], "A new adaptive trait for testing")

    def test_add_trait_invalid_type(self):
        """Test adding a trait with invalid trait_type returns False and does not change the list."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_core_count = len(engine.core_traits)
        initial_adaptive_count = len(engine.adaptive_traits)

        # Define a trait with an invalid trait_type
        new_trait = {
            "trait_name": "invalid_trait",
            "trait_type": "invalid_type",
            "value": 0.5,
            "description": "An invalid trait type"
        }

        # Add the trait
        result = engine.add_trait(new_trait)
        self.assertFalse(result, "Expected add_trait to return False for invalid trait_type")
        self.assertEqual(len(engine.core_traits), initial_core_count,
                         "Expected core traits count to remain the same")
        self.assertEqual(len(engine.adaptive_traits), initial_adaptive_count,
                         "Expected adaptive traits count to remain the same")

    def test_add_trait_missing_name_or_type(self):
        """Test adding a trait missing name or type returns False and does not change the list."""
        engine = PersonalityEngine(seed_path=self.temp_file.name)
        initial_core_count = len(engine.core_traits)
        initial_adaptive_count = len(engine.adaptive_traits)

        # Test missing trait_name
        new_trait1 = {
            "trait_type": "core",
            "value": 0.5,
            "description": "Missing trait name"
        }
        result1 = engine.add_trait(new_trait1)
        self.assertFalse(result1, "Expected add_trait to return False for missing trait_name")
        self.assertEqual(len(engine.core_traits), initial_core_count,
                         "Expected core traits count to remain the same")
        self.assertEqual(len(engine.adaptive_traits), initial_adaptive_count,
                         "Expected adaptive traits count to remain the same")

        # Test missing trait_type
        new_trait2 = {
            "trait_name": "missing_type_trait",
            "value": 0.5,
            "description": "Missing trait type"
        }
        result2 = engine.add_trait(new_trait2)
        self.assertFalse(result2, "Expected add_trait to return False for missing trait_type")
        self.assertEqual(len(engine.core_traits), initial_core_count,
                         "Expected core traits count to remain the same")
        self.assertEqual(len(engine.adaptive_traits), initial_adaptive_count,
                         "Expected adaptive traits count to remain the same")

if __name__ == '__main__':
    unittest.main()