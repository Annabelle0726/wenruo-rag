"""The provider-failure taxonomy, pinned against the wording providers really send.

Written after a live GeminiEmbed refusal (`429 RESOURCE_EXHAUSTED`, quota wording
in the body) was checked end to end: the two classes give the operator OPPOSITE
advice - a spent quota says "change the key or wait for the reset", a pacing limit
says "retry shortly" - so a misclassification is worse than no classification.
"""

import pytest

from common import model_errors


class TestGeminiQuotaWording:
    def test_a_gemini_refusal_that_names_a_spent_quota_is_a_quota_class(self):
        # The live shape: Google's status, the quota wording in the same body.
        detail = (
            "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for "
            "models/gemini-embedding-001"
        )

        assert model_errors.classify(detail) == model_errors.EMBEDDING_QUOTA_EXHAUSTED

    @pytest.mark.parametrize(
        "detail",
        [
            "429 ResourceExhausted: quota exceeded",
            "You have exceeded your quota for this model",
            "embedding quota exhausted",
            "Daily quota exhausted",
            "the account is out of quota",
        ],
    )
    def test_every_quota_wording_is_a_quota_class(self, detail):
        assert model_errors.classify(detail) == model_errors.EMBEDDING_QUOTA_EXHAUSTED

    def test_a_bare_resource_exhausted_stays_ambiguous_and_is_a_rate_limit(self):
        # `RESOURCE_EXHAUSTED` alone is Google's status for BOTH a per-minute
        # limit and a spent daily quota, so it must not be promoted into the
        # quota class: that would tell an operator to change a working key.
        assert (
            model_errors.classify("429 RESOURCE_EXHAUSTED")
            == model_errors.EMBEDDING_RATE_LIMITED
        )
        assert (
            model_errors.classify("RESOURCE_EXHAUSTED: Resource has been exhausted")
            == model_errors.EMBEDDING_RATE_LIMITED
        )

    def test_pacing_wording_is_still_a_rate_limit(self):
        for detail in (
            "429 Too Many Requests",
            "rate limit exceeded",
            "requests per minute exceeded",
            "TPM limit reached",
        ):
            assert (
                model_errors.classify(detail) == model_errors.EMBEDDING_RATE_LIMITED
            )

    def test_an_unrecognised_failure_stays_unclassified(self):
        assert model_errors.classify("connection reset by peer") is None
        assert model_errors.classify("") is None

    def test_both_classes_carry_a_user_safe_message(self):
        for error_class in (
            model_errors.EMBEDDING_QUOTA_EXHAUSTED,
            model_errors.EMBEDDING_RATE_LIMITED,
        ):
            message = model_errors.MESSAGES.get(error_class)
            assert message and message.strip()

    def test_the_raw_body_is_bounded_and_never_the_screen_text(self):
        # A provider body runs to kilobytes and used to reach a notification. The
        # class message is what a reader sees; the raw text is log-only.
        assert model_errors.MAX_RAW_MESSAGE <= 400
        long_detail = "429 RESOURCE_EXHAUSTED quota exhausted " + "x" * 5000
        assert model_errors.classify(long_detail) == model_errors.EMBEDDING_QUOTA_EXHAUSTED
