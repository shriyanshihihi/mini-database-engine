"""B-Tree (CLRS style, minimum degree t) used as the primary-key index.

Every node holds between t-1 and 2t-1 sorted keys (the root may hold fewer).
All leaves are at the same depth, so every search costs O(log N) node visits.
Inside one node we use binary search (bisect), so a lookup is
O(log t * log_t N) = O(log N) comparisons.

Keys -> values.  In the engine: primary key -> byte offset of the row in the data file.
"""
from bisect import bisect_left


class _Node:
    __slots__ = ("keys", "vals", "children", "leaf")

    def __init__(self, leaf=True):
        self.keys = []
        self.vals = []
        self.children = []
        self.leaf = leaf


class BTree:
    def __init__(self, t=32):
        if t < 2:
            raise ValueError("minimum degree t must be >= 2")
        self.t = t
        self.root = _Node(leaf=True)
        self.size = 0
        self.nodes_visited = 0  # instrumentation: lets us *show* O(log N)

    def __len__(self):
        return self.size

    # ---------------------------------------------------------------- search
    def search(self, key):
        """Return the value for key, or None if absent."""
        node = self.root
        while True:
            self.nodes_visited += 1
            i = bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                return node.vals[i]
            if node.leaf:
                return None
            node = node.children[i]

    def __contains__(self, key):
        return self.search(key) is not None

    def height(self):
        h, node = 1, self.root
        while not node.leaf:
            node = node.children[0]
            h += 1
        return h

    # ---------------------------------------------------------------- insert
    def insert(self, key, val):
        """Insert key->val. If key already exists its value is replaced."""
        if self._replace(key, val):
            return
        root = self.root
        if len(root.keys) == 2 * self.t - 1:          # root full -> tree grows in height
            new_root = _Node(leaf=False)
            new_root.children.append(root)
            self._split_child(new_root, 0)
            self.root = new_root
        self._insert_nonfull(self.root, key, val)
        self.size += 1

    def _replace(self, key, val):
        node = self.root
        while True:
            i = bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                node.vals[i] = val
                return True
            if node.leaf:
                return False
            node = node.children[i]

    def _split_child(self, parent, i):
        t = self.t
        full = parent.children[i]
        right = _Node(leaf=full.leaf)
        mid_key, mid_val = full.keys[t - 1], full.vals[t - 1]
        right.keys, right.vals = full.keys[t:], full.vals[t:]
        full.keys, full.vals = full.keys[:t - 1], full.vals[:t - 1]
        if not full.leaf:
            right.children, full.children = full.children[t:], full.children[:t]
        parent.keys.insert(i, mid_key)
        parent.vals.insert(i, mid_val)
        parent.children.insert(i + 1, right)

    def _insert_nonfull(self, node, key, val):
        while True:
            i = bisect_left(node.keys, key)
            if node.leaf:
                node.keys.insert(i, key)
                node.vals.insert(i, val)
                return
            if len(node.children[i].keys) == 2 * self.t - 1:
                self._split_child(node, i)
                if key > node.keys[i]:
                    i += 1
            node = node.children[i]

    # ---------------------------------------------------------------- delete
    def delete(self, key):
        """Remove key. Returns True if it existed."""
        if self.search(key) is None:
            return False
        self._delete(self.root, key)
        if not self.root.keys and not self.root.leaf:  # root emptied -> tree shrinks
            self.root = self.root.children[0]
        self.size -= 1
        return True

    def _delete(self, node, key):
        t = self.t
        i = bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            if node.leaf:                                  # case 1: key in a leaf
                node.keys.pop(i)
                node.vals.pop(i)
            elif len(node.children[i].keys) >= t:          # case 2a: use predecessor
                pk, pv = self._max(node.children[i])
                node.keys[i], node.vals[i] = pk, pv
                self._delete(node.children[i], pk)
            elif len(node.children[i + 1].keys) >= t:      # case 2b: use successor
                sk, sv = self._min(node.children[i + 1])
                node.keys[i], node.vals[i] = sk, sv
                self._delete(node.children[i + 1], sk)
            else:                                          # case 2c: merge and recurse
                self._merge(node, i)
                self._delete(node.children[i], key)
        else:
            if node.leaf:
                return
            if len(node.children[i].keys) < t:             # case 3: make sure child has >= t keys
                i = self._fill(node, i)
            self._delete(node.children[i], key)

    @staticmethod
    def _max(node):
        while not node.leaf:
            node = node.children[-1]
        return node.keys[-1], node.vals[-1]

    @staticmethod
    def _min(node):
        while not node.leaf:
            node = node.children[0]
        return node.keys[0], node.vals[0]

    def _fill(self, node, i):
        t = self.t
        if i > 0 and len(node.children[i - 1].keys) >= t:               # borrow from left sibling
            child, sib = node.children[i], node.children[i - 1]
            child.keys.insert(0, node.keys[i - 1])
            child.vals.insert(0, node.vals[i - 1])
            if not child.leaf:
                child.children.insert(0, sib.children.pop())
            node.keys[i - 1], node.vals[i - 1] = sib.keys.pop(), sib.vals.pop()
        elif i < len(node.children) - 1 and len(node.children[i + 1].keys) >= t:  # borrow from right
            child, sib = node.children[i], node.children[i + 1]
            child.keys.append(node.keys[i])
            child.vals.append(node.vals[i])
            if not child.leaf:
                child.children.append(sib.children.pop(0))
            node.keys[i], node.vals[i] = sib.keys.pop(0), sib.vals.pop(0)
        else:                                                           # merge with a sibling
            if i < len(node.children) - 1:
                self._merge(node, i)
            else:
                self._merge(node, i - 1)
                i -= 1
        return i

    @staticmethod
    def _merge(node, i):
        child, sib = node.children[i], node.children[i + 1]
        child.keys.append(node.keys.pop(i))
        child.vals.append(node.vals.pop(i))
        child.keys.extend(sib.keys)
        child.vals.extend(sib.vals)
        child.children.extend(sib.children)
        node.children.pop(i + 1)

    # ------------------------------------------------------------ iteration
    def items(self):
        """All (key, value) pairs in sorted key order."""
        return self.range(None, None)

    def range(self, lo=None, hi=None):
        """Yield (key, value) with lo <= key <= hi in sorted order (None = unbounded)."""
        yield from self._range(self.root, lo, hi)

    def _range(self, node, lo, hi):
        n = len(node.keys)
        start = 0 if lo is None else bisect_left(node.keys, lo)
        for i in range(start, n):
            if not node.leaf:
                yield from self._range(node.children[i], lo, hi)
            if hi is not None and node.keys[i] > hi:
                return
            yield node.keys[i], node.vals[i]
        if not node.leaf:
            yield from self._range(node.children[n], lo, hi)

    # ----------------------------------------------------------- validation
    def check_invariants(self):
        """Raise AssertionError if any B-Tree rule is broken (used in tests)."""
        leaf_depths = set()

        def walk(node, depth, lo, hi, is_root):
            assert node.keys == sorted(node.keys), "keys not sorted"
            assert len(node.keys) == len(node.vals)
            assert len(node.keys) <= 2 * self.t - 1, "node overfull"
            if not is_root:
                assert len(node.keys) >= self.t - 1, "node underfull"
            for k in node.keys:
                assert (lo is None or k > lo) and (hi is None or k < hi), "key outside range"
            if node.leaf:
                leaf_depths.add(depth)
                assert not node.children
            else:
                assert len(node.children) == len(node.keys) + 1
                bounds = [lo] + node.keys + [hi]
                for j, c in enumerate(node.children):
                    walk(c, depth + 1, bounds[j], bounds[j + 1], False)

        walk(self.root, 0, None, None, True)
        assert len(leaf_depths) == 1, "leaves at different depths"
