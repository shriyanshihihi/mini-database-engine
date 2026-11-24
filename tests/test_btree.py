import random
import pytest
from minidb import BTree


@pytest.mark.parametrize("t", [2, 3, 8, 32])
def test_random_ops_match_dict_model(t):
    rnd, b, model = random.Random(t), BTree(t), {}
    for step in range(5000):
        k = rnd.randint(0, 700)
        if rnd.random() < 0.55:
            b.insert(k, k * 2); model[k] = k * 2
        else:
            assert b.delete(k) == (k in model); model.pop(k, None)
        if step % 400 == 0:
            b.check_invariants()
    b.check_invariants()
    assert len(b) == len(model)
    assert list(b.items()) == sorted(model.items())
    assert list(b.range(100, 300)) == [(k, v) for k, v in sorted(model.items()) if 100 <= k <= 300]


def test_height_is_logarithmic():
    b = BTree(t=32)
    for i in range(100_000):
        b.insert(i, i)
    assert b.height() <= 4            # 32-ary tree: 100K keys fit in ~4 levels
    b.nodes_visited = 0
    b.search(77_777)
    assert b.nodes_visited == b.height()


def test_upsert_replaces_value():
    b = BTree(); b.insert(1, "a"); b.insert(1, "b")
    assert len(b) == 1 and b.search(1) == "b"
