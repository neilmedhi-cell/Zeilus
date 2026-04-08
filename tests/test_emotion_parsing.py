"""
Test script for EmotionResponse parsing.
"""

import sys
import os

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.brain import Brain, EmotionResponse

def test_parse_valid_emotion():
    raw = '''Wait wait that's actually genius!
<EMOTION>{"emotion": "excited", "intensity": 0.9, "valence": 0.8, "arousal": 0.6}</EMOTION>'''
    
    resp = Brain._parse_emotion_tag(raw)
    assert resp.text == "Wait wait that's actually genius!"
    assert resp.emotion == "excited"
    assert resp.intensity == 0.9
    assert resp.valence == 0.8
    assert resp.arousal == 0.6
    assert resp.has_emotion is True
    print("PASS: Valid emotion")

def test_parse_missing_emotion():
    raw = "Just a normal response without tags."
    resp = Brain._parse_emotion_tag(raw)
    assert resp.text == "Just a normal response without tags."
    assert resp.emotion == "neutral"
    assert resp.has_emotion is False
    print("PASS: Missing emotion")

def test_parse_malformed_json():
    raw = '''Broken JSON
<EMOTION>{emotion: excited, "intensity": }</EMOTION>'''
    resp = Brain._parse_emotion_tag(raw)
    assert resp.text == "Broken JSON"
    assert resp.emotion == "neutral"
    print("PASS: Malformed JSON handled gracefully")

if __name__ == "__main__":
    print("Running Emotion parsing tests...")
    test_parse_valid_emotion()
    test_parse_missing_emotion()
    test_parse_malformed_json()
    print("ALL TESTS PASSED")
