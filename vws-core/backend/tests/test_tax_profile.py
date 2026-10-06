"""TX-08: owner defaults, explicit overrides and unavailable-rate boundaries."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.config import Settings
from backend.domain.tax_profile import EXTERNAL_LOT_REMINDERS, TaxProfile


def test_owner_profile_default_has_no_invented_federal_rates() -> None:
    profile = Settings().tax_profile
    assert profile.filing_status == "single"
    assert profile.state == "Texas"
    assert profile.state_rate == profile.niit_rate == Decimal("0")
    assert profile.federal_st_rate is profile.federal_lt_rate is None
    assert not profile.estimate_available
    assert len(EXTERNAL_LOT_REMINDERS) == 3
    assert "401(k)" in EXTERNAL_LOT_REMINDERS[-1]


def test_tx_08_explicit_environment_rates_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "TAX_FED_ST_RATE": "0.24",
        "TAX_FED_LT_RATE": "0.15",
        "TAX_STATE_RATE": "0",
        "TAX_NIIT_RATE": "0.038",
    }.items():
        monkeypatch.setenv(name, value)
    profile = Settings().tax_profile
    assert profile.estimate_available
    assert profile.federal_st_rate == Decimal("0.24")
    assert profile.federal_lt_rate == Decimal("0.15")
    assert profile.niit_rate == Decimal("0.038")


@pytest.mark.parametrize("value", [True, 0.24, "NaN", "Infinity", "-0.01", "1.01", "bad"])
def test_tx_08_invalid_rates_are_rejected(value: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(tax_fed_st_rate=value)
    with pytest.raises(ValidationError):
        TaxProfile(federal_lt_rate=value)


def test_tx_08_state_changes_cannot_silently_keep_texas_default() -> None:
    with pytest.raises(ValidationError):
        Settings(tax_state="Other")
    with pytest.raises(ValidationError):
        TaxProfile(state="Other")
    assert Settings(tax_state="Other", tax_state_rate=None).tax_profile.state_rate is None


def test_tx_08_unknown_state_or_niit_rate_disables_estimate() -> None:
    assert not TaxProfile(
        federal_st_rate=Decimal(0), federal_lt_rate=Decimal(0), state_rate=None
    ).estimate_available
    assert not TaxProfile(
        federal_st_rate=Decimal(0), federal_lt_rate=Decimal(0), niit_rate=None
    ).estimate_available
    assert TaxProfile(federal_st_rate=Decimal(0), federal_lt_rate=Decimal(0)).estimate_available


def test_profile_frozen_extra_forbid_revalidated_at_settings_boundary() -> None:
    with pytest.raises(ValidationError):
        TaxProfile.model_validate({"unknown": "value"})
    with pytest.raises(ValidationError):
        TaxProfile().state = "Other"
    corrupted = Settings.model_construct(tax_fed_st_rate=Decimal("NaN"))
    with pytest.raises(ValidationError):
        _ = corrupted.tax_profile
