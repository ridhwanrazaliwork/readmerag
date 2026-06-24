from main import is_time_query, is_global_list_query, is_personal_query
from markdown_cleaner import clean_markdown_for_rag


class TestTimeQuery:
    def test_latest_repo(self):
        assert is_time_query("What is your latest repo?") is True

    def test_newest_repo(self):
        assert is_time_query("show me the newest project") is True

    def test_recently_updated(self):
        assert is_time_query("what was recently updated?") is True

    def test_not_time_query(self):
        assert is_time_query("Show me code syntax") is False

    def test_non_time_context(self):
        assert is_time_query("tell me about your data pipeline") is False


class TestGlobalListQuery:
    def test_list_all(self):
        assert is_global_list_query("List all my projects please") is True

    def test_all_repos(self):
        assert is_global_list_query("show me all your repos") is True

    def test_not_list(self):
        assert is_global_list_query("what is airflow about?") is False


class TestPersonalQuery:
    def test_experience(self):
        assert is_personal_query("Where did you go to school?") is True

    def test_work(self):
        assert is_personal_query("what is your work experience?") is True

    def test_skills(self):
        assert is_personal_query("what skills do you have?") is True

    def test_not_personal(self):
        assert is_personal_query("what does the data pipeline do?") is False


class TestEmptyReadmePlaceholder:
    def test_placeholder_threshold_under_30(self):
        tiny = "# Hi"
        cleaned = clean_markdown_for_rag(tiny)
        assert len(cleaned.strip()) < 30

    def test_no_placeholder_above_30(self):
        real = "# Project\n\nThis is a real project with a detailed README.\n\n## Features\n- Feature 1\n- Feature 2"
        cleaned = clean_markdown_for_rag(real)
        assert len(cleaned.strip()) >= 30


class TestMarkdownCleaner:
    def test_strips_images(self):
        result = clean_markdown_for_rag('![badge](https://img.shields.io/badge/Python-3776AB)')
        assert 'img.shields.io' not in result

    def test_strips_html_img(self):
        result = clean_markdown_for_rag('<img src="badge.svg"/>Text remains')
        assert '<img' not in result
        assert 'Text remains' in result

    def test_strips_badge_container(self):
        result = clean_markdown_for_rag('<p align="center"><img src="demo.gif"/></p>Text')
        assert '<p' not in result
        assert 'Text' in result.strip()

    def test_strips_emojis(self):
        result = clean_markdown_for_rag('Hello \U0001f680 world')
        assert '\U0001f680' not in result
        assert 'Hello' in result

    def test_collapses_whitespace(self):
        result = clean_markdown_for_rag('Line1\n\n\n\nLine2')
        assert '\n\n\n' not in result
        assert 'Line1\n\nLine2' in result
