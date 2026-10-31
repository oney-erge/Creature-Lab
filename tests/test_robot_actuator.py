"""The XL330 servo model must match the BAM package it reimplements.

Expected values were produced by ``bam.model.load_model("xl330", "m6")`` (Rhoban/bam, commit
62bd8ce) with ``kp=200, vin=7.4``; a 500-state comparison against the package was exact.
"""

import numpy as np
import pytest

from creature_lab.robots.actuator import M6, ServoBank, friction_budget

TARGET = np.array([0.5, -0.3, 0.1])
Q = np.array([0.1, 0.2, -0.4])
DQ = np.array([1.0, -2.0, 0.5])


def test_torque_matches_bam():
    bank = ServoBank(3)
    torque = bank.torque(TARGET, Q, DQ)
    assert torque == pytest.approx([0.1741145267, -0.1819048489, 0.2533814678], abs=1e-9)


def test_battery_sags_with_load_like_bam():
    bank = ServoBank(3)
    first = bank.torque(TARGET, Q, DQ)
    assert bank.effective_voltage() == pytest.approx(7.4 - 0.1 * np.abs(first).sum())
    assert bank.effective_voltage() == pytest.approx(7.339059915668843)
    second = bank.torque(TARGET, Q, DQ)
    assert second == pytest.approx([0.1722882544, -0.1796220086, 0.2510986274], abs=1e-9)


def test_battery_never_sags_below_its_floor():
    bank = ServoBank(14, sag_v_per_nm=100.0)
    bank.torque(np.ones(14), np.zeros(14), np.zeros(14))
    assert bank.effective_voltage() == 6.0


def test_friction_budget_matches_bam():
    loss, damping = friction_budget(
        np.array([0.3, -0.1, 0.5]), np.array([-0.2, 0.2, 0.4]), np.array([0.0, 1.5, -3.0])
    )
    assert loss == pytest.approx([0.1058402382, 0.0523142595, 0.1474498779], abs=1e-9)
    assert damping == pytest.approx(M6["friction_viscous"])


def test_stall_torque_is_full_voltage_over_resistance():
    assert ServoBank(1, battery_v=7.4).stall_torque == pytest.approx(7.4 * M6["kt"] / M6["R"])


def test_holding_still_at_target_needs_no_torque():
    torque = ServoBank(2).torque(np.zeros(2), np.zeros(2), np.zeros(2))
    assert torque == pytest.approx([0.0, 0.0])
