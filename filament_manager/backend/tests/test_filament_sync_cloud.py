"""
Tests for _sync_spool_weight_to_cloud — the fire-and-forget helper that pushes
weight changes for Bambu-linked spools to Bambu Cloud FM.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from app.routers.filament_sync import _sync_spool_weight_to_cloud
from app.models import Spool


def _make_linked_spool(session, *, weight_g: float, cloud_id: str = "42") -> Spool:
    s = Spool(
        brand="Test", material="PLA", color_name="White", color_hex="#FFFFFF",
        initial_weight_g=1000.0, current_weight_g=weight_g,
        bambu_spool_id=cloud_id,
    )
    session.add(s)
    session.commit()
    return s


@pytest.fixture
def mock_session_local(session):
    """Patch SessionLocal in filament_sync to return the test session."""
    mock_sl = MagicMock(return_value=session)
    # Prevent the helper from calling session.close() (which would break the fixture)
    session.close = MagicMock()
    with patch("app.routers.filament_sync.SessionLocal", mock_sl):
        yield session


class TestSyncSpoolWeightToCloud:
    @pytest.mark.asyncio
    async def test_updates_netweight_when_positive(self, mock_session_local):
        spool = _make_linked_spool(mock_session_local, weight_g=500.0, cloud_id="42")

        with patch("app.bambu_cloud_client.update_filament", new_callable=AsyncMock) as mock_update, \
             patch("app.bambu_cloud_client.delete_filaments", new_callable=AsyncMock) as mock_delete:
            await _sync_spool_weight_to_cloud(spool.id)

        mock_update.assert_awaited_once_with("42", {"netWeight": 500})
        mock_delete.assert_not_awaited()
        mock_session_local.refresh(spool)
        assert spool.bambu_spool_id == "42"
        assert spool.bambu_synced_at is not None

    @pytest.mark.asyncio
    async def test_deletes_and_unlinks_when_empty(self, mock_session_local):
        spool = _make_linked_spool(mock_session_local, weight_g=0.0, cloud_id="99")

        with patch("app.bambu_cloud_client.update_filament", new_callable=AsyncMock) as mock_update, \
             patch("app.bambu_cloud_client.delete_filaments", new_callable=AsyncMock) as mock_delete:
            await _sync_spool_weight_to_cloud(spool.id)

        mock_delete.assert_awaited_once_with([99])
        mock_update.assert_not_awaited()
        mock_session_local.refresh(spool)
        assert spool.bambu_spool_id is None
        assert spool.bambu_synced_at is None

    @pytest.mark.asyncio
    async def test_skips_unlinked_spool(self, mock_session_local):
        s = Spool(
            brand="Test", material="PLA", color_name="White", color_hex="#FFFFFF",
            initial_weight_g=1000.0, current_weight_g=500.0, bambu_spool_id=None,
        )
        mock_session_local.add(s)
        mock_session_local.commit()

        with patch("app.bambu_cloud_client.update_filament", new_callable=AsyncMock) as mock_update, \
             patch("app.bambu_cloud_client.delete_filaments", new_callable=AsyncMock) as mock_delete:
            await _sync_spool_weight_to_cloud(s.id)

        mock_update.assert_not_awaited()
        mock_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_cloud_error(self, mock_session_local):
        spool = _make_linked_spool(mock_session_local, weight_g=300.0, cloud_id="7")

        with patch("app.bambu_cloud_client.update_filament",
                   new_callable=AsyncMock,
                   side_effect=HTTPException(502, "Bambu down")):
            # Must not raise
            await _sync_spool_weight_to_cloud(spool.id)
