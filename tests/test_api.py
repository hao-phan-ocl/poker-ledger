"""End-to-end through the HTTP API."""

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as test_client:
        yield test_client


def new_player(client, name):
    response = client.post("/api/players", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def new_game(client, **kwargs):
    body = {"label": "Friday", "default_buy_in_cents": 5000, **kwargs}
    response = client.post("/api/games", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def seat(client, game_id, player_id):
    assert (
        client.post(
            f"/api/games/{game_id}/players", json={"player_id": player_id}
        ).status_code
        == 201
    )


def txn(client, game_id, player_id, kind, cents):
    return client.post(
        f"/api/games/{game_id}/transactions",
        json={"player_id": player_id, "kind": kind, "amount_cents": cents},
    )


class TestFullNight:
    def test_a_whole_game_from_seating_to_settlement(self, client):
        game = new_game(client)
        hao, mia, sam = (new_player(client, n) for n in ("Hao", "Mia", "Sam"))
        for player in (hao, mia, sam):
            seat(client, game, player)
            assert txn(client, game, player, "buy_in", 5000).status_code == 201

        # Hao rebuys after busting the first stack.
        assert txn(client, game, hao, "buy_in", 5000).status_code == 201

        detail = client.get(f"/api/games/{game}").json()
        assert detail["summary"]["total_buy_in_cents"] == 20000

        # 200.00 was bought in, so 200.00 must be counted out.
        txn(client, game, hao, "cash_out", 4000)
        txn(client, game, mia, "cash_out", 12000)
        txn(client, game, sam, "cash_out", 4000)

        summary = client.get(f"/api/games/{game}").json()["summary"]
        assert summary["balanced"]
        assert {r["name"]: r["net_cents"] for r in summary["results"]} == {
            "Hao": -6000,
            "Mia": 7000,
            "Sam": -1000,
        }

        settlement = client.get(f"/api/games/{game}/settlement").json()
        assert settlement["balanced"]
        assert len(settlement["payments"]) == 2
        assert sum(p["amount_cents"] for p in settlement["payments"]) == 7000

        assert (
            client.post(f"/api/games/{game}/close", json={"force": False}).status_code
            == 200
        )

        stats = client.get("/api/players/stats").json()
        assert {s["name"]: s["capital_cents"] for s in stats} == {
            "Hao": -6000,
            "Mia": 7000,
            "Sam": -1000,
        }

    def test_closing_short_books_is_refused_until_forced(self, client):
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)
        txn(client, game, hao, "buy_in", 5000)
        txn(client, game, hao, "cash_out", 4000)

        refused = client.post(f"/api/games/{game}/close", json={"force": False})
        assert refused.status_code == 400
        assert "short" in refused.json()["detail"]

        assert (
            client.post(f"/api/games/{game}/close", json={"force": True}).status_code
            == 200
        )


class TestDiscardingAGame:
    def _finished_game(self, client, label):
        game = new_game(client, label=label)
        for name, cashed in (("Hao", 15000), ("Mia", 5000)):
            existing = {p["name"]: p["id"] for p in client.get("/api/players").json()}
            player = existing.get(name) or new_player(client, name)
            seat(client, game, player)
            txn(client, game, player, "buy_in", 10000)
            txn(client, game, player, "cash_out", cashed)
        client.post(f"/api/games/{game}/close", json={"force": False})
        return game

    def test_a_discarded_game_drops_out_of_the_stats(self, client):
        self._finished_game(client, "Real night")
        mistake = self._finished_game(client, "Test run")

        before = {
            s["name"]: s["capital_cents"] for s in client.get("/api/players/stats").json()
        }
        assert before == {"Hao": 10000, "Mia": -10000}

        response = client.post(f"/api/games/{mistake}/void", json={"reason": "test run"})
        assert response.status_code == 200
        assert response.json()["voided"] == 1

        after = {
            s["name"]: s["capital_cents"] for s in client.get("/api/players/stats").json()
        }
        assert after == {"Hao": 5000, "Mia": -5000}

    def test_it_can_be_restored(self, client):
        game = self._finished_game(client, "Real night")
        client.post(f"/api/games/{game}/void", json={"reason": "mistake"})
        assert client.get("/api/players/stats").json() == []

        assert client.post(f"/api/games/{game}/restore").status_code == 200
        assert len(client.get("/api/players/stats").json()) == 2

    def test_a_discarded_game_is_still_listed(self, client):
        game = self._finished_game(client, "Test run")
        client.post(f"/api/games/{game}/void", json={"reason": "test run"})
        listed = client.get("/api/games").json()
        assert len(listed) == 1
        assert listed[0]["voided"] == 1
        assert listed[0]["void_reason"] == "test run"

    def test_an_empty_game_can_be_deleted(self, client):
        game = new_game(client, label="Created by accident")
        assert client.delete(f"/api/games/{game}").status_code == 200
        assert client.get("/api/games").json() == []

    def test_a_game_with_money_can_also_be_deleted(self, client):
        """Discard keeps the history; delete is for a game that should never
        have existed. Both are offered - this one is not reversible."""
        keep = self._finished_game(client, "Real night")
        mistake = self._finished_game(client, "Entered wrong")

        assert client.delete(f"/api/games/{mistake}").status_code == 200
        assert [g["id"] for g in client.get("/api/games").json()] == [keep]
        assert client.get(f"/api/games/{mistake}").status_code == 400

        stats = client.get("/api/players/stats").json()
        assert all(s["games_played"] == 1 for s in stats)


class TestGameListing:
    def test_live_games_come_first(self, client):
        """A game left running is the thing you most need to see."""
        old = new_game(client, label="Last week")
        hao = new_player(client, "Hao")
        seat(client, old, hao)
        txn(client, old, hao, "buy_in", 5000)
        txn(client, old, hao, "cash_out", 5000)
        client.post(f"/api/games/{old}/close", json={"force": False})

        newer = new_game(client, label="Also closed")
        client.post(f"/api/games/{newer}/close", json={"force": False})
        running = new_game(client, label="Still going")

        listed = [g["id"] for g in client.get("/api/games").json()]
        assert listed[0] == running, "the live game should be at the top"

    def test_two_games_may_share_a_name_and_stay_distinct(self, client):
        """Only players are unique by name. Two Fridays can share one."""
        first = new_game(client, label="Friday game")
        second = new_game(client, label="Friday game")
        assert first != second
        assert len(client.get("/api/games").json()) == 2

    def test_two_games_can_be_live_at_once(self, client):
        """Running a test game alongside a real one is allowed."""
        a = new_game(client, label="Real")
        b = new_game(client, label="Testing")
        live = [g["id"] for g in client.get("/api/games").json() if g["status"] == "live"]
        assert sorted(live) == sorted([a, b])


class TestUndoingAnEntry:
    def test_a_new_entry_comes_back_with_its_id(self, client):
        """The page needs the id to offer an undo for what was just added."""
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)

        body = txn(client, game, hao, "buy_in", 5000).json()
        assert isinstance(body["transaction_id"], int)
        assert body["summary"]["total_buy_in_cents"] == 5000

    def test_undoing_reverses_it_completely(self, client):
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)
        txn(client, game, hao, "buy_in", 5000)
        mistake = txn(client, game, hao, "buy_in", 5000).json()["transaction_id"]

        assert client.delete(f"/api/transactions/{mistake}").status_code == 200
        summary = client.get(f"/api/games/{game}").json()["summary"]
        assert summary["total_buy_in_cents"] == 5000
        assert len(client.get(f"/api/games/{game}").json()["transactions"]) == 1

    def test_an_entry_cannot_be_undone_once_the_game_is_closed(self, client):
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)
        entry = txn(client, game, hao, "buy_in", 5000).json()["transaction_id"]
        txn(client, game, hao, "cash_out", 5000)
        client.post(f"/api/games/{game}/close", json={"force": False})

        response = client.delete(f"/api/transactions/{entry}")
        assert response.status_code == 400
        assert "closed" in response.json()["detail"]


class TestValidationThroughTheApi:
    def test_duplicate_player_names_are_rejected(self, client):
        new_player(client, "Hao")
        response = client.post("/api/players", json={"name": "Hao"})
        assert response.status_code == 400
        assert "already a player" in response.json()["detail"]

    def test_an_unseated_player_cannot_transact(self, client):
        game = new_game(client)
        outsider = new_player(client, "Passerby")
        response = txn(client, game, outsider, "buy_in", 5000)
        assert response.status_code == 400
        assert "not in this game" in response.json()["detail"]

    def test_unknown_game_is_a_400_not_a_crash(self, client):
        assert client.get("/api/games/999").status_code == 400

    def test_bad_transaction_kind_is_rejected_by_the_schema(self, client):
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)
        response = txn(client, game, hao, "donation", 5000)
        assert response.status_code == 422


class TestOddsEndpoint:
    def test_a_made_straight_flush_never_loses(self, client):
        response = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": ["Qs", "Js", "Ts", "2d", "3c"],
                "opponents": 3,
                "trials": 2000,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["win"] == 1.0
        assert body["made_hand"] == "straight flush"

    def test_draws_are_reported_on_the_flop(self, client):
        body = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": ["Qs", "Js", "2h"],
                "opponents": 2,
                "trials": 5000,
            },
        ).json()
        assert body["street"] == "flop"
        draws = {d["description"]: d["outs"] for d in body["draws"]}
        assert draws["flush"] == 8
        assert draws["straight flush"] == 1

    def test_pot_odds_are_returned_when_a_price_is_given(self, client):
        body = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": ["Qs", "Js", "2h"],
                "opponents": 1,
                "trials": 5000,
                "pot_cents": 10000,
                "to_call_cents": 2500,
            },
        ).json()
        assert body["pot_odds"]["required_equity"] == pytest.approx(0.2)
        assert body["pot_odds"]["profitable"] is True

    def test_pot_odds_are_omitted_when_no_price_is_given(self, client):
        body = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": [],
                "opponents": 1,
                "trials": 2000,
            },
        ).json()
        assert "pot_odds" not in body

    def test_a_card_cannot_be_in_two_places(self, client):
        response = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": ["As", "Js", "2h"],
                "opponents": 1,
                "trials": 2000,
            },
        )
        assert response.status_code == 400
        assert "hand and on the board" in response.json()["detail"]

    def test_a_nonsense_card_is_rejected_with_a_useful_message(self, client):
        response = client.post(
            "/api/odds",
            json={
                "hole": ["Xs", "Ks"],
                "board": [],
                "opponents": 1,
                "trials": 2000,
            },
        )
        assert response.status_code == 400
        assert "unknown rank" in response.json()["detail"]

    def test_an_impossible_board_is_rejected(self, client):
        response = client.post(
            "/api/odds",
            json={
                "hole": ["As", "Ks"],
                "board": ["Qs", "Js"],
                "opponents": 1,
                "trials": 2000,
            },
        )
        assert response.status_code == 400


class TestExport:
    def test_csv_export_carries_every_row(self, client):
        game = new_game(client)
        hao = new_player(client, "Hao")
        seat(client, game, hao)
        txn(client, game, hao, "buy_in", 5000)
        txn(client, game, hao, "cash_out", 7500)

        response = client.get("/api/export.csv")
        assert response.status_code == 200
        lines = response.text.strip().splitlines()
        assert lines[0].startswith("game,started_at")
        assert len(lines) == 3
        assert "50.00" in lines[1] and "75.00" in lines[2]

    def test_json_export_has_the_three_tables(self, client):
        new_game(client)
        body = client.get("/api/export.json").json()
        assert set(body) == {"players", "games", "transactions"}


def test_the_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Poker Ledger" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
