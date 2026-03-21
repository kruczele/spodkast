"""
Unit tests for the two-stage localization pipeline.

These tests use mocks and do NOT require real API keys.
"""

from unittest.mock import MagicMock, patch, call
import pytest

from app.script_generator import (
    translate_script,
    localize_script,
    translate_and_localize,
    TRANSLATE_SYSTEM_TEMPLATE,
    LOCALIZE_SYSTEM_TEMPLATE,
    LANGUAGE_NAMES,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_message(text: str):
    """Build a minimal mock of an Anthropic message response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


# ── translate_script ──────────────────────────────────────────────────────────

class TestTranslateScript:
    def test_calls_anthropic_with_correct_system_prompt(self):
        """translate_script should call the API with the translation system prompt."""
        translated_text = "Wszechświat zaczął się 13,8 miliarda lat temu."
        mock_msg = _make_mock_message(translated_text)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = mock_msg

            result = translate_script(
                text="The universe began 13.8 billion years ago.",
                target_language="pl",
                api_key="test-key",
            )

        assert result == translated_text
        create_call = instance.messages.create.call_args
        assert LANGUAGE_NAMES["pl"] in create_call.kwargs["system"]
        assert "Translate" in create_call.kwargs["system"]

    def test_returns_translated_text(self):
        expected = "Hola mundo"
        mock_msg = _make_mock_message(expected)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = mock_msg

            result = translate_script("Hello world", "es", "key")

        assert result == expected

    def test_uses_lang_name_not_code(self):
        """The system prompt must contain the full language name, not the code."""
        mock_msg = _make_mock_message("Hallo Welt")

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = mock_msg

            translate_script("Hello world", "de", "key")

        system = instance.messages.create.call_args.kwargs["system"]
        assert "German" in system
        assert " de " not in system.lower().replace("German", "")


# ── localize_script ───────────────────────────────────────────────────────────

class TestLocalizeScript:
    def test_calls_anthropic_with_localization_system_prompt(self):
        """localize_script should use the localization/rewrite system prompt."""
        localized_text = "Wszechświat zaczął istnieć 13,8 miliarda lat temu."
        mock_msg = _make_mock_message(localized_text)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = mock_msg

            result = localize_script(
                translated_text="Wszechświat zaczął się 13,8 miliarda lat temu.",
                target_language="pl",
                api_key="test-key",
            )

        assert result == localized_text
        system = instance.messages.create.call_args.kwargs["system"]
        # The localization prompt instructs native rewriting, not translation
        assert "native" in system.lower() or "idiomatic" in system.lower() or "natural" in system.lower()
        assert "Polish" in system

    def test_returns_localized_text(self):
        expected = "El mundo dice hola"
        mock_msg = _make_mock_message(expected)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = mock_msg

            result = localize_script("Hola mundo", "es", "key")

        assert result == expected


# ── translate_and_localize (two-stage) ───────────────────────────────────────

class TestTranslateAndLocalize:
    def test_calls_both_stages_in_order(self):
        """translate_and_localize must run Stage 1 then Stage 2 in sequence."""
        stage1_output = "Dosłowne tłumaczenie."
        stage2_output = "Naturalne brzmienie po polsku."

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call = Stage 1 (translate), second = Stage 2 (localize)
            text = stage1_output if call_count == 1 else stage2_output
            return _make_mock_message(text)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.side_effect = fake_create

            result = translate_and_localize(
                text="This is an English podcast script.",
                target_language="pl",
                api_key="test-key",
            )

        assert result == stage2_output
        assert call_count == 2, "Expected exactly two LLM calls (Stage 1 + Stage 2)"

    def test_stage2_receives_stage1_output(self):
        """Stage 2 must receive Stage 1's output as its input, not the original text."""
        original_english = "Original English text."
        stage1_output = "Przetłumaczony tekst."
        stage2_output = "Naturalnie brzmiący tekst po polsku."

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_message(stage1_output)
            else:
                # Verify the user message is Stage 1 output, not original
                user_msg = kwargs["messages"][0]["content"]
                assert user_msg == stage1_output, (
                    f"Stage 2 received wrong input: expected stage1 output "
                    f"'{stage1_output}', got '{user_msg}'"
                )
                return _make_mock_message(stage2_output)

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.side_effect = fake_create

            result = translate_and_localize(original_english, "pl", "test-key")

        assert result == stage2_output

    def test_stage1_system_prompt_differs_from_stage2(self):
        """The two stages must use distinct system prompts."""
        systems_used = []

        def fake_create(**kwargs):
            systems_used.append(kwargs.get("system", ""))
            return _make_mock_message("text")

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.side_effect = fake_create

            translate_and_localize("Hello world", "pl", "key")

        assert len(systems_used) == 2
        assert systems_used[0] != systems_used[1], "Stage 1 and Stage 2 must use different system prompts"
        # Stage 1 prompt should mention translation
        assert "Translate" in systems_used[0] or "translate" in systems_used[0]

    def test_error_in_stage1_propagates(self):
        """If Stage 1 raises, translate_and_localize should propagate the error."""
        import anthropic as _a

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.side_effect = _a.RateLimitError(
                message="rate limited", response=MagicMock(status_code=429), body={}
            )
            with pytest.raises(RuntimeError, match="rate limit"):
                translate_and_localize("text", "pl", "key")

    def test_error_in_stage2_propagates(self):
        """If Stage 2 raises, translate_and_localize should propagate the error."""
        import anthropic as _a

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_message("stage1 done")
            raise _a.RateLimitError(
                message="rate limited", response=MagicMock(status_code=429), body={}
            )

        with patch("app.script_generator.anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.side_effect = fake_create

            with pytest.raises(RuntimeError, match="rate limit"):
                translate_and_localize("text", "pl", "key")


# ── Prompt template sanity checks ────────────────────────────────────────────

class TestPromptTemplates:
    def test_translate_template_contains_lang_name_placeholder(self):
        rendered = TRANSLATE_SYSTEM_TEMPLATE.format(lang_name="Polish")
        assert "Polish" in rendered
        assert "{lang_name}" not in rendered

    def test_localize_template_contains_lang_name_placeholder(self):
        rendered = LOCALIZE_SYSTEM_TEMPLATE.format(lang_name="Polish")
        assert "Polish" in rendered
        assert "{lang_name}" not in rendered

    def test_localize_template_mentions_rewriting_not_translating(self):
        rendered = LOCALIZE_SYSTEM_TEMPLATE.format(lang_name="Polish")
        lowered = rendered.lower()
        # Should mention rewriting/naturalness, not just translation
        assert any(kw in lowered for kw in ["rewrite", "natural", "idiomatic", "native"])

    @pytest.mark.parametrize("lang_code,lang_name", list(LANGUAGE_NAMES.items()))
    def test_all_language_names_render_in_templates(self, lang_code, lang_name):
        t1 = TRANSLATE_SYSTEM_TEMPLATE.format(lang_name=lang_name)
        t2 = LOCALIZE_SYSTEM_TEMPLATE.format(lang_name=lang_name)
        assert lang_name in t1
        assert lang_name in t2
