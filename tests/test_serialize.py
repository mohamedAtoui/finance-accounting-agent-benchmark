"""Serialization round-trips and stays byte-stable per seed."""

from __future__ import annotations

from finbalance.generator import generate_instance
from finbalance.serialize import (
    dumps,
    instance_from_dict,
    instance_to_dict,
    solution_from_dict,
    solution_to_dict,
)


def test_instance_round_trip():
    inst, _ = generate_instance(1)
    assert instance_from_dict(instance_to_dict(inst)) == inst


def test_solution_round_trip():
    _, gt = generate_instance(1)
    assert solution_from_dict(solution_to_dict(gt)) == gt


def test_serialization_is_byte_stable():
    a, ga = generate_instance(5)
    b, gb = generate_instance(5)
    assert dumps(instance_to_dict(a)) == dumps(instance_to_dict(b))
    assert dumps(solution_to_dict(ga)) == dumps(solution_to_dict(gb))
