from analysis.handoff import clean_description, pick_angle
from analysis.text import similarity, tokens, topic_query


def test_topic_query_strips_noise():
    assert topic_query("Secret codes for ChatGPT & Claude 😳") == "Secret codes for ChatGPT & Claude"
    assert topic_query("The AI Millionaire Formula: 4 Steps (2026)") == "The AI Millionaire Formula: 4 Steps"


def test_similarity_rewards_title_keyword_overlap():
    assert similarity("Secret codes for ChatGPT & Claude", "", "ChatGPT secret codes you must know", "") >= 0.5
    assert similarity("Secret codes for ChatGPT & Claude", "", "How to bake bread", "sourdough") == 0.0
    assert "chatgpt" in tokens("Secret codes for ChatGPT")


def test_clean_description_removes_links_emails_promos():
    desc = "Join my community: https://x.com/y\nCode NATE for 10% off\n\nI gave the model one prompt and it built the whole video from scratch, here is how.\n\nSponsorship: nate@example.com"
    out = clean_description(desc)
    assert "http" not in out and "@" not in out and "Code NATE" not in out
    assert "one prompt" in out


def test_pick_angle():
    assert pick_angle("12 Ways to Make Money") == "listicle"
    assert pick_angle("How I'd Start a Business") == "how-to"
    assert pick_angle("Why I'm Switching") == "concept"
