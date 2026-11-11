"""Write ``policy.onnx``: a stand-still policy for the example robot, with no ONNX library.

It maps the 27 observation numbers to 6 actions with one weight matrix and one bias. Here both are
zero, so the policy always answers "hold the default pose". It exists so the example runs end to
end; a real policy comes from your own training. The ONNX file is encoded by hand, so this script
needs only numpy.

    python make_policy.py          # writes policy.onnx next to this file
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

FLOAT = 1  # ONNX TensorProto.FLOAT


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _number(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _bytes(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _text(field: int, value: str) -> bytes:
    return _bytes(field, value.encode())


def _tensor(name: str, array: np.ndarray) -> bytes:
    body = b"".join(_number(1, dim) for dim in array.shape)
    body += _number(2, FLOAT) + _text(8, name)
    return body + _bytes(9, array.astype("<f4").tobytes())


def _value_info(name: str, width: int) -> bytes:
    dims = _bytes(1, _number(1, 1)) + _bytes(1, _number(1, width))  # shape [1, width]
    tensor_type = _number(1, FLOAT) + _bytes(2, dims)
    return _text(1, name) + _bytes(2, _bytes(1, tensor_type))


def _node(op: str, inputs: list[str], output: str) -> bytes:
    return b"".join(_text(1, name) for name in inputs) + _text(2, output) + _text(4, op)


def policy_bytes(
    weight: np.ndarray, bias: np.ndarray, metadata: dict[str, str] | None = None
) -> bytes:
    """An ONNX model computing ``action = observation @ weight + bias``.

    ``metadata`` becomes the model's metadata (what mjlab and Pollen Robotics write).
    """
    inputs, outputs = weight.shape
    graph = _bytes(1, _node("MatMul", ["observation", "weight"], "hidden"))
    graph += _bytes(1, _node("Add", ["hidden", "bias"], "action"))
    graph += _text(2, "policy")
    graph += _bytes(5, _tensor("weight", weight)) + _bytes(5, _tensor("bias", bias))
    graph += _bytes(11, _value_info("observation", inputs))
    graph += _bytes(12, _value_info("action", outputs))
    model = _number(1, 8) + _text(2, "creature-lab-example")
    model += _bytes(8, _number(2, 13)) + _bytes(7, graph)
    for key, value in (metadata or {}).items():
        model += _bytes(14, _text(1, key) + _text(2, value))
    return model


if __name__ == "__main__":
    target = Path(__file__).with_name("policy.onnx")
    target.write_bytes(policy_bytes(np.zeros((27, 6)), np.zeros(6)))
    print(f"wrote {target} ({target.stat().st_size} bytes)")
