# pyright: basic
"""Execute the script's color evaluator with importer-shaped nodes, without Blender."""

import ast
from pathlib import Path
from types import SimpleNamespace as Node
from typing import Any

import numpy as np
import pytest


def evaluator():
    path = Path(__file__).resolve().parents[1] / "blender" / "split_scripted.py"
    tree = ast.parse(path.read_text())
    functions: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    scope: dict[str, Any] = {"np": np}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), scope)
    return scope["base_color"], scope["srgb_to_linear"]


def socket(value=(1, 1, 1, 1), node=None):
    return Node(default_value=value, links=[] if node is None else [Node(from_node=node)])


@pytest.mark.parametrize("kind", ["MIX", "MIX_RGB"])
def test_texture_factor_is_multiplied_in_linear_space(kind):
    evaluate, decode = evaluator()
    image = Node(type="TEX_IMAGE", image=object())
    inputs = [socket(1)] + [socket() for _ in range(7)]
    left, right = (6, 7) if kind == "MIX" else (1, 2)
    inputs[left], inputs[right] = socket(node=image), socket((0.01, 0.01, 0.01, 1))
    multiply = Node(type=kind, blend_type="MULTIPLY", inputs=inputs)
    shader = Node(type="BSDF_PRINCIPLED", inputs={"Base Color": socket(node=multiply)})
    material = Node(node_tree=Node(nodes=[shader, multiply, image]))
    # White texture times .01 linear factor yields .09985 encoded: dark greenhouse glass.
    result = evaluate(material, lambda _image: decode(np.ones((1, 3))))
    assert result[0] == pytest.approx([0.09985282] * 3)
    assert result.mean() < 0.2
    # Mid-gray must be decoded before multiplication, then encoded exactly once.
    result = evaluate(material, lambda _image: decode(np.full((1, 3), 0.5)))
    assert result[0] == pytest.approx([0.02765411535] * 3)
