"""Heap file: an append-only file of variable-length records.

File layout
-----------
  [8-byte magic "MINIDB01"]
  record*  where record = [1 byte live-flag][4 byte big-endian payload length][payload bytes]

* live-flag 1 = live row, 0 = deleted (tombstone).
* A record's *offset* (position of its flag byte) is its address. The B-Tree index
  stores primary_key -> offset, so one lookup = O(log N) index work + ONE seek+read.
* Updates append a new record and tombstone the old one (no in-place growth).
* Deleted space is reclaimed by Table.compact().
"""
import os
import struct

MAGIC = b"MINIDB01"
_HDR = struct.Struct(">BI")  # flag, length


class HeapFile:
    def __init__(self, path, sync=False):
        self.path = path
        self.sync = sync                      # fsync after every write (durable but slow)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.f = open(path, "w+b" if new else "r+b")
        if new:
            self.f.write(MAGIC)
            self.f.flush()
        else:
            if self.f.read(len(MAGIC)) != MAGIC:
                raise ValueError(f"{path} is not a minidb data file")
        self.f.seek(0, os.SEEK_END)

    def append(self, payload: bytes) -> int:
        self.f.seek(0, os.SEEK_END)
        offset = self.f.tell()
        self.f.write(_HDR.pack(1, len(payload)) + payload)
        self.f.flush()
        if self.sync:
            os.fsync(self.f.fileno())
        return offset

    def read(self, offset: int):
        """Return payload at offset, or None if the record is a tombstone."""
        self.f.seek(offset)
        flag, length = _HDR.unpack(self.f.read(_HDR.size))
        payload = self.f.read(length)
        return payload if flag == 1 else None

    def tombstone(self, offset: int):
        self.f.seek(offset)
        self.f.write(b"\x00")
        self.f.flush()
        if self.sync:
            os.fsync(self.f.fileno())

    def scan(self):
        """Sequentially yield (offset, payload) for every LIVE record. O(N)."""
        self.f.flush()
        with open(self.path, "rb") as g:      # separate handle: scan never disturbs the writer's position
            g.seek(len(MAGIC))
            offset = len(MAGIC)
            while True:
                head = g.read(_HDR.size)
                if len(head) < _HDR.size:
                    return
                flag, length = _HDR.unpack(head)
                payload = g.read(length)
                if flag == 1:
                    yield offset, payload
                offset += _HDR.size + length

    def size(self):
        self.f.flush()
        return os.path.getsize(self.path)

    def close(self):
        if not self.f.closed:
            self.f.flush()
            self.f.close()
