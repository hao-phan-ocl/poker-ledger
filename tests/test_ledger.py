"""Ledger and settlement."""

import sqlite3

import pytest

from app import ledger, stats
from app.db import connect
from app.ledger import LedgerError, format_money


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def game(conn):
    return ledger.create_game(
        conn, "Friday game", currency="EUR", default_buy_in_cents=5000
    )


def seat(conn, game_id, name):
    player_id = ledger.create_player(conn, name)
    ledger.seat_player(conn, game_id, player_id)
    return player_id


def play(conn, game_id, name, bought, cashed):
    """Seat a player, buy them in, and cash them out."""
    player_id = seat(conn, game_id, name)
    ledger.buy_in(conn, game_id, player_id, bought)
    ledger.cash_out(conn, game_id, player_id, cashed)
    return player_id


class TestPlayers:
    def test_names_are_unique(self, conn):
        ledger.create_player(conn, "Hao")
        with pytest.raises(LedgerError, match="already a player"):
            ledger.create_player(conn, "Hao")

    def test_a_name_is_required(self, conn):
        with pytest.raises(LedgerError, match="needs a name"):
            ledger.create_player(conn, "   ")


class TestTransactions:
    def test_net_is_cash_out_minus_buy_in(self, conn, game):
        player = seat(conn, game, "Hao")
        ledger.buy_in(conn, game, player, 5000)
        ledger.buy_in(conn, game, player, 5000)  # a rebuy
        ledger.cash_out(conn, game, player, 12500)

        result = ledger.game_summary(conn, game).results[0]
        assert result.buy_in_cents == 10000
        assert result.cash_out_cents == 12500
        assert result.net_cents == 2500

    def test_a_busted_player_cashes_out_zero(self, conn, game):
        player = seat(conn, game, "Hao")
        ledger.buy_in(conn, game, player, 5000)
        ledger.cash_out(conn, game, player, 0)
        assert ledger.game_summary(conn, game).results[0].net_cents == -5000

    def test_amounts_must_make_sense(self, conn, game):
        player = seat(conn, game, "Hao")
        with pytest.raises(LedgerError, match="more than zero"):
            ledger.buy_in(conn, game, player, 0)
        with pytest.raises(LedgerError, match="cannot be negative"):
            ledger.cash_out(conn, game, player, -100)

    def test_players_must_be_seated_first(self, conn, game):
        outsider = ledger.create_player(conn, "Passerby")
        with pytest.raises(LedgerError, match="not in this game"):
            ledger.buy_in(conn, game, outsider, 5000)

    def test_a_closed_game_is_read_only(self, conn, game):
        player = play(conn, game, "Hao", 5000, 5000)
        ledger.close_game(conn, game)
        with pytest.raises(LedgerError, match="closed"):
            ledger.buy_in(conn, game, player, 5000)

    def test_a_mistake_can_be_deleted(self, conn, game):
        player = seat(conn, game, "Hao")
        txn_id = ledger.buy_in(conn, game, player, 5000)
        ledger.buy_in(conn, game, player, 5000)
        ledger.delete_txn(conn, txn_id)
        assert ledger.game_summary(conn, game).results[0].buy_in_cents == 5000

    def test_a_player_with_money_in_cannot_be_unseated(self, conn, game):
        player = seat(conn, game, "Hao")
        ledger.buy_in(conn, game, player, 5000)
        with pytest.raises(LedgerError, match="already has transactions"):
            ledger.unseat_player(conn, game, player)


class TestChipConservation:
    def test_balanced_books_are_recognised(self, conn, game):
        play(conn, game, "Hao", 10000, 15000)
        play(conn, game, "Mia", 10000, 5000)
        summary = ledger.game_summary(conn, game)
        assert summary.balanced
        assert summary.discrepancy_cents == 0

    def test_a_short_table_is_flagged(self, conn, game):
        play(conn, game, "Hao", 10000, 12000)
        play(conn, game, "Mia", 10000, 6500)
        summary = ledger.game_summary(conn, game)
        assert not summary.balanced
        assert summary.discrepancy_cents == -1500
        assert "short" in summary.balance_message
        assert "15.00" in summary.balance_message

    def test_an_over_counted_table_is_flagged(self, conn, game):
        play(conn, game, "Hao", 10000, 15000)
        play(conn, game, "Mia", 10000, 7000)
        summary = ledger.game_summary(conn, game)
        assert summary.discrepancy_cents == 2000
        assert "over" in summary.balance_message

    def test_players_still_to_cash_out_are_listed(self, conn, game):
        play(conn, game, "Hao", 10000, 10000)
        pending = seat(conn, game, "Mia")
        ledger.buy_in(conn, game, pending, 10000)
        assert ledger.game_summary(conn, game).awaiting_cash_out == ["Mia"]

    def test_unbalanced_books_cannot_be_closed(self, conn, game):
        play(conn, game, "Hao", 10000, 9000)
        with pytest.raises(LedgerError, match="short"):
            ledger.close_game(conn, game)
        ledger.close_game(conn, game, force=True)
        assert ledger.get_game(conn, game)["status"] == "closed"


class TestSettlement:
    def test_losers_pay_winners(self, conn, game):
        play(conn, game, "Hao", 10000, 15000)
        play(conn, game, "Mia", 10000, 10000)
        play(conn, game, "Sam", 10000, 5000)

        settlement = ledger.settle(conn, game)
        assert settlement.balanced
        assert len(settlement.payments) == 1
        payment = settlement.payments[0]
        assert (payment.from_name, payment.to_name) == ("Sam", "Hao")
        assert payment.amount_cents == 5000

    def test_every_balance_is_cleared_in_at_most_n_minus_one_payments(self, conn, game):
        play(conn, game, "Hao", 10000, 20000)
        play(conn, game, "Mia", 10000, 15000)
        play(conn, game, "Sam", 10000, 5000)
        play(conn, game, "Kim", 10000, 0)

        settlement = ledger.settle(conn, game)
        assert len(settlement.payments) <= 3

        # Applying every payment must leave nobody owing anything.
        balances = {r.name: r.net_cents for r in ledger.game_summary(conn, game).results}
        for payment in settlement.payments:
            balances[payment.from_name] += payment.amount_cents
            balances[payment.to_name] -= payment.amount_cents
        assert all(value == 0 for value in balances.values()), balances

    def test_no_payments_are_offered_when_the_books_do_not_balance(self, conn, game):
        """A wrong payment list would move real money to the wrong people."""
        play(conn, game, "Hao", 10000, 15000)
        play(conn, game, "Mia", 10000, 3000)
        settlement = ledger.settle(conn, game)
        assert not settlement.balanced
        assert settlement.payments == []
        assert "short" in settlement.message

    def test_an_even_night_needs_no_payments(self, conn, game):
        play(conn, game, "Hao", 10000, 10000)
        play(conn, game, "Mia", 10000, 10000)
        settlement = ledger.settle(conn, game)
        assert settlement.payments == []
        assert "level" in settlement.message

    def test_adjustments_move_money_between_players(self, conn, game):
        """Hao covers 20.00 of Mia's buy-in."""
        hao = play(conn, game, "Hao", 10000, 10000)
        mia = play(conn, game, "Mia", 10000, 10000)
        ledger.record(conn, game, hao, ledger.ADJUSTMENT, -2000, "covered Mia")
        ledger.record(conn, game, mia, ledger.ADJUSTMENT, 2000, "covered by Hao")

        settlement = ledger.settle(conn, game)
        assert settlement.balanced
        assert len(settlement.payments) == 1
        assert settlement.payments[0].from_name == "Hao"
        assert settlement.payments[0].amount_cents == 2000


class TestLifetimeStats:
    def _closed_game(self, conn, label, results):
        game_id = ledger.create_game(conn, label)
        for name, bought, cashed in results:
            player_id = conn.execute(
                "SELECT id FROM player WHERE name = ?", (name,)
            ).fetchone()
            player_id = player_id[0] if player_id else ledger.create_player(conn, name)
            ledger.seat_player(conn, game_id, player_id)
            ledger.buy_in(conn, game_id, player_id, bought)
            ledger.cash_out(conn, game_id, player_id, cashed)
        ledger.close_game(conn, game_id)
        return game_id

    def test_capital_accumulates_across_games(self, conn):
        self._closed_game(conn, "Week 1", [("Hao", 10000, 15000), ("Mia", 10000, 5000)])
        self._closed_game(conn, "Week 2", [("Hao", 10000, 12000), ("Mia", 10000, 8000)])

        by_name = {s.name: s for s in stats.all_player_stats(conn)}
        assert by_name["Hao"].capital_cents == 7000
        assert by_name["Mia"].capital_cents == -7000
        assert by_name["Hao"].games_played == 2

    def test_the_capital_curve_runs_in_order(self, conn):
        self._closed_game(conn, "Week 1", [("Hao", 10000, 15000), ("Mia", 10000, 5000)])
        self._closed_game(conn, "Week 2", [("Hao", 10000, 6000), ("Mia", 10000, 14000)])

        hao = stats.player_stats(
            conn, conn.execute("SELECT id FROM player WHERE name='Hao'").fetchone()[0]
        )
        assert [s.running_capital_cents for s in hao.sessions] == [5000, 1000]
        assert hao.best_night_cents == 5000
        assert hao.worst_night_cents == -4000

    def test_streaks_count_back_from_the_latest_game(self, conn):
        self._closed_game(conn, "Week 1", [("Hao", 10000, 15000), ("Mia", 10000, 5000)])
        self._closed_game(conn, "Week 2", [("Hao", 10000, 5000), ("Mia", 10000, 15000)])
        self._closed_game(conn, "Week 3", [("Hao", 10000, 4000), ("Mia", 10000, 16000)])

        by_name = {s.name: s for s in stats.all_player_stats(conn)}
        assert by_name["Hao"].streak == stats.Streak("losing", 2)
        assert by_name["Mia"].streak == stats.Streak("winning", 2)

    def test_roi_is_measured_against_money_put_at_risk(self, conn):
        self._closed_game(conn, "Week 1", [("Hao", 10000, 15000), ("Mia", 10000, 5000)])
        by_name = {s.name: s for s in stats.all_player_stats(conn)}
        assert by_name["Hao"].roi == pytest.approx(0.5)
        assert by_name["Mia"].roi == pytest.approx(-0.5)

    def test_live_games_do_not_count_towards_capital(self, conn):
        self._closed_game(conn, "Week 1", [("Hao", 10000, 15000), ("Mia", 10000, 5000)])
        live = ledger.create_game(conn, "Tonight")
        hao = conn.execute("SELECT id FROM player WHERE name='Hao'").fetchone()[0]
        ledger.seat_player(conn, live, hao)
        ledger.buy_in(conn, live, hao, 50000)

        by_name = {s.name: s for s in stats.all_player_stats(conn)}
        assert by_name["Hao"].capital_cents == 5000
        assert by_name["Hao"].games_played == 1


class TestVoiding:
    def _closed_game(self, conn, label):
        game_id = ledger.create_game(conn, label)
        for name, bought, cashed in (("Hao", 10000, 15000), ("Mia", 10000, 5000)):
            row = conn.execute("SELECT id FROM player WHERE name = ?", (name,)).fetchone()
            player_id = row[0] if row else ledger.create_player(conn, name)
            ledger.seat_player(conn, game_id, player_id)
            ledger.buy_in(conn, game_id, player_id, bought)
            ledger.cash_out(conn, game_id, player_id, cashed)
        ledger.close_game(conn, game_id)
        return game_id

    def test_a_voided_game_stops_counting_towards_capital(self, conn):
        self._closed_game(conn, "Real night")
        mistake = self._closed_game(conn, "Test run")
        assert {s.name: s.capital_cents for s in stats.all_player_stats(conn)} == {
            "Hao": 10000,
            "Mia": -10000,
        }

        ledger.void_game(conn, mistake, "test run, not a real game")
        assert {s.name: s.capital_cents for s in stats.all_player_stats(conn)} == {
            "Hao": 5000,
            "Mia": -5000,
        }

    def test_voiding_keeps_the_rows(self, conn):
        game = self._closed_game(conn, "Test run")
        ledger.void_game(conn, game, "test run")
        assert len(ledger.game_transactions(conn, game)) == 4
        row = ledger.get_game(conn, game)
        assert row["voided"] == 1
        assert row["void_reason"] == "test run"

    def test_a_void_can_be_undone(self, conn):
        game = self._closed_game(conn, "Real night")
        ledger.void_game(conn, game, "oops")
        assert stats.all_player_stats(conn) == []
        ledger.restore_game(conn, game)
        assert {s.name: s.capital_cents for s in stats.all_player_stats(conn)} == {
            "Hao": 5000,
            "Mia": -5000,
        }

    def test_a_voided_game_accepts_no_new_money(self, conn, game):
        player = seat(conn, game, "Hao")
        ledger.void_game(conn, game, "abandoned")
        with pytest.raises(LedgerError, match="voided"):
            ledger.buy_in(conn, game, player, 5000)
        with pytest.raises(LedgerError, match="voided"):
            ledger.reopen_game(conn, game)

    def test_an_empty_game_can_be_deleted(self, conn):
        game = ledger.create_game(conn, "Created by accident")
        ledger.delete_game(conn, game)
        with pytest.raises(LedgerError, match="no game with id"):
            ledger.get_game(conn, game)

    def test_deleting_takes_its_transactions_and_seats_with_it(self, conn, game):
        """Nothing may be left orphaned pointing at a game that is gone."""
        player = seat(conn, game, "Hao")
        ledger.buy_in(conn, game, player, 5000)
        ledger.cash_out(conn, game, player, 7000)

        ledger.delete_game(conn, game)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM txn WHERE game_id = ?", (game,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM game_player WHERE game_id = ?", (game,)
            ).fetchone()[0]
            == 0
        )
        # The player themselves survives - they exist beyond any one game.
        assert ledger.get_player(conn, player)["name"] == "Hao"

    def test_deleting_a_closed_game_removes_it_from_capital(self, conn):
        self._closed_game(conn, "Real night")
        mistake = self._closed_game(conn, "Entered wrong")
        assert stats.all_player_stats(conn)[0].games_played == 2

        ledger.delete_game(conn, mistake)
        assert stats.all_player_stats(conn)[0].games_played == 1


class TestMigrations:
    def test_an_existing_database_migrates_forward(self, tmp_path):
        from app import db

        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.executescript(db.MIGRATIONS[0])
        old.execute("PRAGMA user_version = 1")
        old.execute(
            "INSERT INTO game (label, status, started_at) VALUES (?, ?, ?)",
            ("Old night", "closed", "2026-01-01"),
        )
        old.commit()
        old.close()

        migrated = db.connect(path)
        row = migrated.execute("SELECT * FROM game").fetchone()
        assert row["label"] == "Old night"
        assert row["voided"] == 0
        assert row["void_reason"] == ""
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
        migrated.close()

    def test_migrating_twice_changes_nothing(self, tmp_path):
        from app import db

        path = tmp_path / "twice.db"
        first = db.connect(path)
        version = first.execute("PRAGMA user_version").fetchone()[0]
        first.close()

        second = db.connect(path)
        assert second.execute("PRAGMA user_version").fetchone()[0] == version
        second.close()


class TestMoneyFormatting:
    def test_cents_never_become_floats(self):
        assert format_money(123456, "EUR") == "€1,234.56"
        assert format_money(-5000, "USD") == "-$50.00"
        assert format_money(0, "GBP") == "£0.00"

    def test_a_long_night_of_small_amounts_does_not_drift(self, conn, game):
        player = seat(conn, game, "Hao")
        for _ in range(1000):
            ledger.buy_in(conn, game, player, 333)
        assert ledger.game_summary(conn, game).results[0].buy_in_cents == 333000
