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


class FeedForwardOnnxPolicy:
    """Any ONNX policy with one input (observations) and one output (actions)."""

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
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError(
                f"{self.path.name} has {len(inputs)} inputs and {len(outputs)} outputs; "
                "Creature Lab runs policies with one input (the observation) and one output "
                "(the action)"
            )
        self._input, self._output = inputs[0].name, outputs[0].name
        self.obs_len = _width(inputs[0].shape)
        self.action_len = _width(outputs[0].shape)

    def reset(self) -> None:  # stateless
        pass

    def act(self, observation: np.ndarray) -> np.ndarray:
        out = self._session.run([self._output], {self._input: observation[None].astype(np.float32)})
        return np.asarray(out[0]).reshape(-1).astype(np.float32)


def _width(shape: list) -> int | None:
    """The last dimension of an ONNX tensor shape, or None when it is symbolic."""
    last = shape[-1] if shape else None
    return int(last) if isinstance(last, int) else None


_RECURRENT_KEYS = (
    "lstm_weight_ih_l0",
    "lstm_weight_hh_l0",
    "lstm_bias_ih_l0",
    "lstm_bias_hh_l0",
    "fc1_weight",
    "fc1_bias",
    "fc2_weight",
    "fc2_bias",
)


class RecurrentNpzPolicy:
    """A one-layer LSTM then a two-layer head with ELU, from a ``.npz`` of weights, in numpy.

    The arrays are the PyTorch ones: ``lstm_weight_ih_l0``, ``lstm_weight_hh_l0``,
    ``lstm_bias_ih_l0``, ``lstm_bias_hh_l0``, ``fc1_weight``, ``fc1_bias``, ``fc2_weight`` and
    ``fc2_bias``. The hidden state starts at zero for every run.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        with np.load(self.path) as arrays:
            absent = [name for name in _RECURRENT_KEYS if name not in arrays.files]
            if absent:
                raise ValueError(f"{self.path.name} lacks the arrays: {', '.join(absent)}")
            self._w = {name: arrays[name].astype(np.float64) for name in arrays.files}
        hidden = self._w["lstm_weight_hh_l0"].shape[1]
        self._hidden = hidden
        self.obs_len = int(self._w["lstm_weight_ih_l0"].shape[1])
        self.action_len = int(self._w["fc2_weight"].shape[0])
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros(self._hidden)
        self._c = np.zeros(self._hidden)

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


class G1WalkPolicy(RecurrentNpzPolicy):
    """Unitree's pretrained G1 walker, bundled with Creature Lab."""

    OBS_LEN = 47

    def __init__(self) -> None:
        data = resources.files("creature_lab.robots").joinpath("data", "unitree_g1_policy.npz")
        with resources.as_file(data) as path:
            super().__init__(path)


def load_policy(path: Path) -> FeedForwardOnnxPolicy | RecurrentNpzPolicy:
    """The policy in ``path``: ``.onnx`` or ``.npz`` (chosen by the file's suffix)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".onnx":
        return FeedForwardOnnxPolicy(path)
    if suffix == ".npz":
        return RecurrentNpzPolicy(path)
    raise ValueError(
        f"{Path(path).name}: policies must be .onnx or .npz files "
        "(a PyTorch .pt file needs converting first; see docs/ROBOT_PACKS.md)"
    )
