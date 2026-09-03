"""
Tests for the streamer module (VolumeTracker delta logic & BinanceStreamer cooldown)
"""
import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.streamer import VolumeTracker, BinanceStreamer


def make_ticker(symbol: str, price: float, cum_quote_volume: float) -> dict:
    """Membuat ticker ala Binance !ticker@arr"""
    return {
        "s": symbol,
        "c": str(price),          # last price
        "q": str(cum_quote_volume),  # cumulative 24h quote volume
    }


class TestVolumeTracker:
    """Test logika volume delta (bug lama: membandingkan kumulatif vs kumulatif)"""

    def test_update_ticker_records_delta_not_absolute(self):
        tracker = VolumeTracker(window_minutes=5)

        # Snapshot kumulatif 24 jam yang normal (angka besar)
        tracker.update_ticker("BTCUSDT", make_ticker("BTCUSDT", 50000, 1_000_000))
        tracker.update_ticker("BTCUSDT", make_ticker("BTCUSDT", 50000, 1_000_500))
        tracker.update_ticker("BTCUSDT", make_ticker("BTCUSDT", 50000, 1_001_200))

        deltas = [vol for _, vol in tracker.volume_deltas["BTCUSDT"]]
        # Delta harus KECIL (selisih antar snapshot), bukan angka kumulatif jutaan
        assert deltas == [500.0, 700.0]

    def test_volume_spike_detected_on_delta_surge(self):
        tracker = VolumeTracker(window_minutes=5)

        # Baseline: 6 interval normal dengan delta ~100
        cum = 0.0
        for i in range(7):
            cum += 100.0
            tracker.update_ticker("TESTUSDT", make_ticker("TESTUSDT", 1.0, cum))

        # Lonjakan: delta 2000 (20x baseline) -> spike >= 300%
        cum += 2000.0
        tracker.update_ticker("TESTUSDT", make_ticker("TESTUSDT", 1.0, cum))

        spike = tracker.calculate_volume_spike("TESTUSDT")
        assert spike is not None
        assert spike >= 300.0, f"Expected spike >= 300%, got {spike}"

    def test_volume_spike_none_when_stable(self):
        tracker = VolumeTracker(window_minutes=5)
        cum = 0.0
        for i in range(7):
            cum += 100.0
            tracker.update_ticker("STABLEUSDT", make_ticker("STABLEUSDT", 1.0, cum))
        spike = tracker.calculate_volume_spike("STABLEUSDT")
        # Delta konsisten -> spike mendekati 0, jauh dari threshold
        assert spike is not None and spike < 50

    def test_insufficient_data_returns_none(self):
        tracker = VolumeTracker(window_minutes=5)
        assert tracker.calculate_volume_spike("NEWUSDT") is None
        tracker.update_ticker("NEWUSDT", make_ticker("NEWUSDT", 1.0, 100))
        assert tracker.calculate_volume_spike("NEWUSDT") is None

    def test_negative_delta_ignored(self):
        """Rolling 24h window Binance bisa membuat delta negatif - harus diabaikan"""
        tracker = VolumeTracker(window_minutes=5)
        tracker.update_ticker("NEGUSDT", make_ticker("NEGUSDT", 1.0, 1000))
        tracker.update_ticker("NEGUSDT", make_ticker("NEGUSDT", 1.0, 900))  # turun!
        tracker.update_ticker("NEGUSDT", make_ticker("NEGUSDT", 1.0, 950))
        deltas = [vol for _, vol in tracker.volume_deltas["NEGUSDT"]]
        assert deltas == [50.0]  # hanya delta positif yang tercatat

    def test_zero_baseline_returns_none(self):
        tracker = VolumeTracker(window_minutes=5)
        tracker.update_ticker("ZEROUSDT", make_ticker("ZEROUSDT", 1.0, 0))
        tracker.update_ticker("ZEROUSDT", make_ticker("ZEROUSDT", 1.0, 0))
        tracker.update_ticker("ZEROUSDT", make_ticker("ZEROUSDT", 1.0, 500))
        # Baseline semua nol -> tidak bisa hitung spike
        assert tracker.calculate_volume_spike("ZEROUSDT") is None

    def test_old_data_pruned_from_window(self):
        tracker = VolumeTracker(window_minutes=1)  # window 60 detik
        tracker.update_ticker("OLDUSDT", make_ticker("OLDUSDT", 1.0, 100))
        # Simulasikan timestamp lama
        old_ts = time.time() - 3600
        tracker.volume_deltas["OLDUSDT"].append((old_ts, 999.0))
        # Update baru memicu pembersihan
        tracker.update_ticker("OLDUSDT", make_ticker("OLDUSDT", 1.0, 200))
        timestamps = [ts for ts, _ in tracker.volume_deltas["OLDUSDT"]]
        assert all(ts > time.time() - 120 for ts in timestamps)

    def test_get_current_price(self):
        tracker = VolumeTracker()
        tracker.update_ticker("PXUSDT", make_ticker("PXUSDT", 12345.678, 100))
        assert tracker.get_current_price("PXUSDT") == 12345.678
        assert tracker.get_current_price("UNKNOWNUSDT") is None

    def test_get_volume_stats(self):
        tracker = VolumeTracker()
        cum = 100.0
        tracker.update_ticker("STATUSDT", make_ticker("STATUSDT", 1.0, cum))  # baseline (tanpa delta)
        for delta in (100.0, 200.0, 300.0):
            cum += delta
            tracker.update_ticker("STATUSDT", make_ticker("STATUSDT", 1.0, cum))
        stats = tracker.get_volume_stats("STATUSDT")
        assert stats["data_points"] == 3
        assert stats["min_volume"] == 100.0
        assert stats["max_volume"] == 300.0
        assert stats["avg_volume"] == 200.0


class TestBinanceStreamer:
    """Test cooldown mechanics"""

    @pytest.fixture
    def streamer(self):
        s = BinanceStreamer(db=MagicMock(), anomaly_callback=AsyncMock())
        return s

    @pytest.mark.asyncio
    async def test_cooldown_add_and_check(self, streamer):
        assert not streamer._is_in_cooldown("BTCUSDT")
        streamer._add_to_cooldown("BTCUSDT")
        assert streamer._is_in_cooldown("BTCUSDT")
        # Cleanup
        for task in list(streamer._cooldown_tasks):
            task.cancel()

    @pytest.mark.asyncio
    async def test_cooldown_task_keeps_reference(self, streamer):
        """Bug lama: task cooldown dibuat tanpa referensi (risiko GC)"""
        streamer._add_to_cooldown("ETHUSDT")
        assert len(streamer._cooldown_tasks) == 1
        # Cleanup
        for task in list(streamer._cooldown_tasks):
            task.cancel()

    @pytest.mark.asyncio
    async def test_stop_cancels_cooldown_tasks(self, streamer):
        streamer._add_to_cooldown("ADAUSDT")
        streamer.running = True
        await streamer.stop()
        assert len(streamer._cooldown_tasks) == 0
        assert streamer.running is False

    @pytest.mark.asyncio
    async def test_process_message_stream_format(self, streamer):
        """Format payload Binance !ticker@arr (list of tickers)"""
        streamer.volume_tracker = MagicMock()
        streamer.volume_tracker.update_ticker = MagicMock()
        streamer.volume_tracker.calculate_volume_spike = MagicMock(return_value=None)

        msg = '{"stream":"!ticker@arr","data":[{"s":"BTCUSDT","c":"50000","q":"1000"}]}'
        await streamer._process_message(msg)
        streamer.volume_tracker.update_ticker.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_invalid_json_no_crash(self, streamer):
        await streamer._process_message("bukan json {{{")  # tidak raise

    @pytest.mark.asyncio
    async def test_non_usdt_pairs_skipped(self, streamer):
        streamer.volume_tracker = MagicMock()
        await streamer._process_ticker({"s": "ETHBTC", "c": "0.05", "q": "10"})
        streamer.volume_tracker.update_ticker.assert_not_called()
