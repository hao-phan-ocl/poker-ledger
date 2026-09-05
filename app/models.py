"""Request models. Responses are the dataclasses from ledger, stats and equity."""

from pydantic import BaseModel, Field

from .ledger import KINDS


class NewPlayer(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    notes: str = ""


class NewGame(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    location: str = ""
    currency: str = Field(default="EUR", max_length=8)
    small_blind_cents: int = Field(default=0, ge=0)
    big_blind_cents: int = Field(default=0, ge=0)
    default_buy_in_cents: int = Field(default=0, ge=0)


class SeatRequest(BaseModel):
    player_id: int
    seat: int | None = None


class NewTransaction(BaseModel):
    player_id: int
    kind: str = Field(pattern=f"^({'|'.join(KINDS)})$")
    # Signed, for adjustments. The ledger applies the per-kind rules.
    amount_cents: int
    note: str = ""


class CloseRequest(BaseModel):
    force: bool = False


class VoidRequest(BaseModel):
    reason: str = Field(default="", max_length=200)


class OddsRequest(BaseModel):
    hole: list[str] = Field(min_length=2, max_length=2)
    board: list[str] = Field(default_factory=list, max_length=5)
    opponents: int = Field(default=1, ge=1, le=9)
    # 50k trials lands inside +/-0.25% in well under a second.
    trials: int = Field(default=50_000, ge=1_000, le=1_000_000)
    pot_cents: int | None = Field(default=None, ge=0)
    to_call_cents: int | None = Field(default=None, ge=0)
