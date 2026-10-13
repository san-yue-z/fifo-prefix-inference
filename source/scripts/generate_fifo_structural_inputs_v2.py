"""Generate and lock new factorial inputs without running any measured actor."""

from collections import Counter
from fractions import Fraction as F
import hashlib
from itertools import permutations, product
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "protocols/fifo_structural_inputs_v2.json"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")


def draw(block, n, purpose, index, modulus):
    payload = f"fifo-structural-v2:{block}:{n}:{purpose}:{index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % modulus


def ledger(block, n, bits):
    t = F(0)
    result = []
    choices = (F(1, 2), F(3, 4), F(1), F(5, 4), F(3, 2))
    for index in range(n):
        if index:
            t += F(1, 2) + F(draw(block, n, "gap", index, 257), 256)
            if bits == 40:
                t += F(2 * draw(block, n, "fine", index, 128) + 1, 2**40)
        result.append([str(t), str(choices[draw(block, n, "work", index, 5)])])
    return result


def prior(components):
    result = []
    slope = F(1, 8)
    for index in range(components):
        lower = F(0) if components == 1 else F(index, 4)
        width = F(7, 8) if components == 1 else F(1, 8)
        vertices = [(F(1, 2), lower), (F(3, 2), lower + slope),
                    (F(3, 2), lower + slope + width), (F(1, 2), lower + width)]
        planes = [(1, 0, F(3, 2), False), (-1, 0, -F(1, 2), False),
                  (slope, -1, slope / 2 - lower, index % 2 == 0),
                  (-slope, 1, lower + width - slope / 2, index % 2 == 1)]
        result.append({"vertices": [[str(x), str(y)] for x, y in vertices],
                       "halfplanes": [[str(a), str(b), str(c), strict] for a, b, c, strict in planes]})
    return result


def literal_departures(jobs, theta=F(1), delta=F(5, 8)):
    result = []
    for t, p in jobs:
        arrival = F(t) + delta
        result.append(max(arrival, result[-1] if result else arrival) + theta * F(p))
    return result


def contains_prior(cells, theta=F(1), delta=F(5, 8)):
    return any(all(F(a) * theta + F(b) * delta < F(c) if strict else
                   F(a) * theta + F(b) * delta <= F(c)
                   for a, b, c, strict in cell["halfplanes"]) for cell in cells)


def stages(jobs, m, contradictory):
    departures = literal_departures(jobs)
    previous_now = F(0)
    result = []
    last_submit = F(jobs[-1][0])
    query_cycle = ((F(3, 2), F(3)), (F(3), F(4)), (F(4), F(2)))
    for index in range(m):
        count = index * len(jobs) // (m - 1)
        tau = departures[-1] + F(1, 4) if count == len(jobs) else (
            departures[0] / 2 if count == 0 else (departures[count - 1] + departures[count]) / 2)
        if sum(value <= tau for value in departures) != count:
            raise AssertionError("Generated count does not match literal FIFO")
        now = max(last_submit + F(1, 16), tau + F(1, 16), previous_now + F(1, 16))
        local, offset = query_cycle[index % 3]
        result.append({"report": [count, str(tau)],
                       "query": [str(now), "1", str(local), str(now + offset)],
                       "nominal_count_verified": True})
        previous_now = now
    if contradictory:
        result.append({"report": [0, result[-1]["report"][1]],
                       "query": [str(previous_now + F(1, 16)), "1", "3/2", str(previous_now + F(49, 16))],
                       "nominal_count_verified": False, "intentional_contradiction": True})
    return result


def generate():
    orders = tuple(permutations(METHODS))
    inputs = []
    for block_index, block in enumerate(range(2026101301, 2026101307)):
        for n, m, components, bits, family in product((32, 128), (8, 32), (1, 4), (8, 40),
                                                     ("consistent", "contradictory")):
            jobs, cells = ledger(block, n, bits), prior(components)
            if not contains_prior(cells):
                raise AssertionError("Generation witness is outside the prior")
            inputs.append({"id": f"b{block}-n{n}-m{m}-c{components}-p{bits}-{family}",
                           "factors": {"block": block, "n": n, "m": m, "components": components,
                                       "precision_bits": bits, "family": family},
                           "method_order": list(orders[block_index]), "jobs": jobs, "cells": cells,
                           "stages": stages(jobs, m, family == "contradictory")})
    frequencies = Counter(tuple(case["factors"][key] for key in
                                ("n", "m", "components", "precision_bits", "family")) for case in inputs)
    if len(inputs) != 192 or set(frequencies.values()) != {6}:
        raise AssertionError("Incomplete factorial")
    return {"schema": "fifo_structural_inputs_v2", "fixed_date": "2026-10-13",
            "selection": "Prospective full factorial, all method permutations, no actor runs",
            "generation_witness_not_actor_input": {"theta": "1", "delta": "5/8"},
            "inputs": inputs}


def main():
    if OUTPUT.exists():
        raise FileExistsError("Never overwrite locked inputs")
    payload = (json.dumps(generate(), indent=2) + "\n").encode("ascii")
    OUTPUT.write_bytes(payload)
    print(json.dumps({"inputs": 192, "controllers": 576, "sha256": hashlib.sha256(payload).hexdigest(),
                      "output": str(OUTPUT), "actor_calls": 0}))


if __name__ == "__main__":
    main()
