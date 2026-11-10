"""Run trained walking policies without a deep-learning framework."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import numpy as np


class OnnxPolicy:
    """A Microduck-style ONNX policy: 61 observations in, 14 joint offsets out."""

    def __init__(self, path: Path) -> None:
        try:
            import onnxruntime
        except ImportError as error:  # pragma: no cover - exercised by the CLI message
            raise RuntimeError(
                "onnxruntime is missing; install it with: uv sync --extra robots"
            ) from error
        self.path = Path(path)
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        self._session = onnxruntime.InferenceSession(
            str(self.path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name
        self._output = self._session.get_outputs()[0].name
        meta = self._session.get_modelmeta().custom_metadata_map
        self.obs_len = int(self._session.get_inputs()[0].shape[1])
        self.action_scale = float(meta.get("action_scale", 1.0))
        self.joint_names = meta["joint_names"].split(",")
        self.default_pose = np.array(
            [float(value) for value in meta["default_joint_pos"].split(",")], dtype=np.float32
        )
        # The wiring in ``microduck.py`` matches this layout; refuse anything else.
        expected = "base_ang_vel,projected_gravity,joint_pos,joint_vel,actions,command"
        if not meta.get("observation_names", "").startswith(expected):
            raise ValueError(f"{self.path.name} has an observation layout Creature Lab can't wire")

    def reset(self) -> None:  # stateless
        pass

    def act(self, observation: np.ndarray) -> np.ndarray:
        out = self._session.run([self._output], {self._input: observation[None].astype(np.float32)})
        return out[0].squeeze(0).astype(np.float32)


class G1WalkPolicy:
    """Unitree's pretrained G1 walker: an LSTM then a small head, in plain numpy."""

    OBS_LEN = 47

    def __init__(self) -> None:
        data = resources.files("creature_lab.robots").joinpath("data", "unitree_g1_policy.npz")
        with resources.as_file(data) as path, np.load(path) as arrays:
            self._w = {name: arrays[name].astype(np.float64) for name in arrays.files}
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros(64)
        self._c = np.zeros(64)

    def act(self, observation: np.ndarray) -> np.ndarray:
        w = self._w
        gates = (
            w["lstm_weight_ih_l0"] @ observation
            + w["lstm_bias_ih_l0"]
            + w["lstm_weight_hh_l0"] @ self._h
            + w["lstm_bias_hh_l0"]
        )
        i, f, g, o = np.split(gates, 4)
        self._c = _sigmoid(f) * self._c + _sigmoid(i) * np.tanh(g)
        self._h = _sigmoid(o) * np.tanh(self._c)
        hidden = w["fc1_weight"] @ self._h + w["fc1_bias"]
        hidden = np.where(hidden > 0, hidden, np.expm1(np.minimum(hidden, 0)))  # ELU
        return (w["fc2_weight"] @ hidden + w["fc2_bias"]).astype(np.float32)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))
