"""
Tests for ha_publisher._compute() — spool inventory/consumed sensors and
printer status sensors.

The AMS-unmatched section and the printer status section both iterate
PrinterConfig rows. Tests that don't add PrinterConfig records skip those
sections automatically (no bambu_cloud_client calls → no mock needed).
Tests that DO add PrinterConfig records patch get_ams_detail_for_serial
and get_printer_cloud_status to avoid real network calls.
"""
import pytest
from unittest.mock import patch
from app.ha_publisher import _compute
from app.models import PrinterConfig, Spool


def _make_spool(session, *, material: str, weight_g: float, archived: bool = False) -> Spool:
    s = Spool(
        brand="Test",
        material=material,
        color_name="White",
        color_hex="#FFFFFF",
        initial_weight_g=weight_g,
        current_weight_g=weight_g,
        archived=archived,
    )
    session.add(s)
    session.commit()
    return s


class TestLowStockSensor:
    def test_spools_list_includes_grams(self, session):
        s = Spool(brand="Jayo", material="PETG", color_name="Black",
                  color_hex="#000000", initial_weight_g=1000.0, current_weight_g=148.7,
                  archived=False)
        session.add(s); session.commit()

        _, attrs = _compute(session)["sensor.filament_manager_low_stock_spools"]

        assert attrs["spools"] == ["Jayo PETG Black (149g)"]


class TestSpoolInventorySensor:
    def test_total_counts_only_non_archived(self, session):
        _make_spool(session, material="PLA",  weight_g=1000)
        _make_spool(session, material="PLA",  weight_g=200)
        _make_spool(session, material="PETG", weight_g=800, archived=True)  # archived — excluded

        state, attrs = _compute(session)["sensor.filament_manager_total_spools"]

        assert state == 2
        assert attrs["by_material"] == {"PLA": 2}

    def test_total_by_material_sorted(self, session):
        _make_spool(session, material="PETG", weight_g=500)
        _make_spool(session, material="ABS",  weight_g=500)
        _make_spool(session, material="PLA",  weight_g=500)

        state, attrs = _compute(session)["sensor.filament_manager_total_spools"]

        assert state == 3
        assert list(attrs["by_material"].keys()) == ["ABS", "PETG", "PLA"]

    def test_total_empty_inventory(self, session):
        state, attrs = _compute(session)["sensor.filament_manager_total_spools"]

        assert state == 0
        assert attrs["by_material"] == {}


class TestSpoolConsumedSensor:
    def test_consumed_counts_zero_weight_spools(self, session):
        _make_spool(session, material="PLA",  weight_g=0)     # empty, active
        _make_spool(session, material="PLA",  weight_g=0, archived=True)  # empty, archived
        _make_spool(session, material="PETG", weight_g=500)   # still has filament

        state, attrs = _compute(session)["sensor.filament_manager_consumed_spools"]

        assert state == 2
        assert attrs["by_material"] == {"PLA": 2}

    def test_consumed_excludes_spools_with_remaining_weight(self, session):
        _make_spool(session, material="PLA", weight_g=50)   # low but not empty
        _make_spool(session, material="PLA", weight_g=1000)

        state, _ = _compute(session)["sensor.filament_manager_consumed_spools"]

        assert state == 0

    def test_consumed_empty_inventory(self, session):
        state, attrs = _compute(session)["sensor.filament_manager_consumed_spools"]

        assert state == 0
        assert attrs["by_material"] == {}


def _make_printer(session, *, name: str, serial: str) -> PrinterConfig:
    p = PrinterConfig(name=name, bambu_serial=serial, bambu_source="cloud", is_active=True)
    session.add(p)
    session.commit()
    return p


class TestPrinterStatusSensor:
    _PATCH_AMS  = "app.bambu_cloud_client.get_ams_detail_for_serial"
    _PATCH_STAT = "app.bambu_cloud_client.get_printer_cloud_status"

    def test_running_printer(self, session):
        _make_printer(session, name="My P1S", serial="SN001")
        cloud = {"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 30, "subtask_name": "benchy.3mf"}

        with patch(self._PATCH_AMS, return_value={}), patch(self._PATCH_STAT, return_value=cloud):
            result = _compute(session)

        state, attrs = result["sensor.filament_manager_printer_my_p1s_status"]
        assert state == "running"
        assert attrs["mc_percent"] == 42
        assert attrs["mc_remaining_time"] == 30
        assert attrs["subtask_name"] == "benchy.3mf"
        assert attrs["gcode_state"] == "RUNNING"

    def test_idle_printer(self, session):
        _make_printer(session, name="My P1S", serial="SN001")

        with patch(self._PATCH_AMS, return_value={}), patch(self._PATCH_STAT, return_value={"gcode_state": "IDLE"}):
            result = _compute(session)

        state, _ = result["sensor.filament_manager_printer_my_p1s_status"]
        assert state == "idle"

    def test_offline_printer_no_mqtt_data(self, session):
        _make_printer(session, name="My P1S", serial="SN001")

        with patch(self._PATCH_AMS, return_value={}), patch(self._PATCH_STAT, return_value={}):
            result = _compute(session)

        state, attrs = result["sensor.filament_manager_printer_my_p1s_status"]
        assert state == "offline"
        assert attrs["gcode_state"] is None

    def test_entity_id_sanitizes_printer_name(self, session):
        _make_printer(session, name="P1S Pro #1", serial="SN002")

        with patch(self._PATCH_AMS, return_value={}), patch(self._PATCH_STAT, return_value={}):
            result = _compute(session)

        assert "sensor.filament_manager_printer_p1s_pro_1_status" in result

    def test_multiple_printers_get_separate_entities(self, session):
        _make_printer(session, name="Printer A", serial="SNA")
        _make_printer(session, name="Printer B", serial="SNB")
        statuses = {"SNA": {"gcode_state": "RUNNING"}, "SNB": {"gcode_state": "IDLE"}}

        with patch(self._PATCH_AMS, return_value={}), \
             patch(self._PATCH_STAT, side_effect=lambda s: statuses.get(s, {})):
            result = _compute(session)

        assert result["sensor.filament_manager_printer_printer_a_status"][0] == "running"
        assert result["sensor.filament_manager_printer_printer_b_status"][0] == "idle"

    def test_printer_without_serial_is_skipped(self, session):
        p = PrinterConfig(name="No Serial", bambu_serial=None, bambu_source="cloud", is_active=True)
        session.add(p); session.commit()

        with patch(self._PATCH_AMS, return_value={}), patch(self._PATCH_STAT, return_value={}):
            result = _compute(session)

        assert not any("no_serial" in k for k in result)
