"""Generates the PNG diagrams used in README and the interview PDF. Run: python docs/make_diagrams.py"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.dirname(__file__)
C = {"client": "#E8F0FE", "api": "#FFF4D6", "engine": "#E3F6E8", "disk": "#F3E8FF", "pg": "#FDE7E7", "line": "#333333"}


def box(ax, x, y, w, h, text, color, fs=10, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=color, ec=C["line"], lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal")


def arrow(ax, x1, y1, x2, y2, label=None):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", lw=1.4, color=C["line"]))
    if label:
        ax.text((x1 + x2) / 2 + 0.05, (y1 + y2) / 2 + 0.12, label, fontsize=8, ha="center", style="italic")


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h)); ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); return fig, ax


def architecture():
    fig, ax = canvas(10, 6.2)
    box(ax, 3.5, 5.3, 3, 0.7, "Client (browser / curl / Swagger UI)", C["client"], 10)
    box(ax, 3.0, 4.0, 4, 0.8, "FastAPI app  (minidb/api.py)\nvalidation, routing, HTTP status codes", C["api"], 10, True)
    box(ax, 0.2, 1.7, 4.6, 1.6, "", C["engine"]); ax.text(2.5, 3.1, "OUR ENGINE (minidb/)", ha="center", fontsize=10, fontweight="bold")
    box(ax, 0.4, 2.0, 2.0, 0.8, "Table / Database\n(table.py)", "#FFFFFF", 9)
    box(ax, 2.6, 2.0, 2.0, 0.8, "B-Tree index\n(btree.py)\nkey -> offset", "#FFFFFF", 9)
    box(ax, 0.4, 0.2, 4.2, 0.8, "HeapFile (storage.py)\nusers.dat + users.idx + users.schema.json", C["disk"], 8.5)
    box(ax, 5.4, 1.7, 4.4, 1.6, "", C["pg"]); ax.text(7.6, 3.1, "POSTGRESQL PATH (minidb/pg.py)", ha="center", fontsize=10, fontweight="bold")
    box(ax, 5.6, 2.0, 1.9, 0.8, "psycopg2\nconnection pool", "#FFFFFF", 9)
    box(ax, 7.7, 2.0, 1.9, 0.8, "SQL: CRUD, JOIN,\nBEGIN/COMMIT", "#FFFFFF", 9)
    box(ax, 5.6, 0.2, 4.0, 0.8, "PostgreSQL server (tables, indexes, WAL)", C["pg"], 9)
    arrow(ax, 5, 5.3, 5, 4.8, "HTTP + JSON")
    arrow(ax, 4.0, 4.0, 2.5, 3.3, "/engine/*"); arrow(ax, 6.0, 4.0, 7.6, 3.3, "/pg/*")
    arrow(ax, 2.4, 2.4, 2.6, 2.4); arrow(ax, 1.4, 2.0, 1.4, 1.0); arrow(ax, 3.6, 2.0, 3.0, 1.0)
    arrow(ax, 6.6, 2.0, 6.6, 1.0); arrow(ax, 8.7, 2.0, 8.0, 1.0)
    ax.set_title("Mini Database Engine - architecture", fontsize=12, fontweight="bold")
    fig.savefig(os.path.join(OUT, "architecture.png"), dpi=170, bbox_inches="tight"); plt.close(fig)


def workflow():
    fig, ax = canvas(10, 5.2)
    ax.text(5, 4.95, "Life of a request", ha="center", fontsize=12, fontweight="bold")
    ax.text(0.1, 4.45, "INSERT / UPDATE / DELETE", fontsize=10, fontweight="bold")
    steps = ["validate row\nagainst schema", "B-Tree: PK\nalready there?", "append record\nto .dat file", "B-Tree: PK ->\nnew offset", "return row /\nHTTP 201"]
    for i, s in enumerate(steps):
        box(ax, 0.1 + i * 1.95, 3.35, 1.7, 0.9, s, C["engine"], 9)
        if i: arrow(ax, 0.1 + i * 1.95 - 0.25, 3.8, 0.1 + i * 1.95, 3.8)
    ax.text(0.1, 2.75, "SELECT by primary key", fontsize=10, fontweight="bold")
    steps = ["HTTP GET\n/rows/42", "B-Tree search\nO(log N) nodes", "offset found?\n(else 404)", "seek + read ONE\nrecord from .dat", "decode JSON\nreturn row"]
    for i, s in enumerate(steps):
        box(ax, 0.1 + i * 1.95, 1.7, 1.7, 0.9, s, C["api"] if i != 1 else "#D6F5DD", 9)
        if i: arrow(ax, 0.1 + i * 1.95 - 0.25, 2.15, 0.1 + i * 1.95, 2.15)
    ax.text(0.1, 1.1, "SELECT on a non-indexed column", fontsize=10, fontweight="bold")
    steps = ["WHERE city='Pune'", "no index on city", "scan .dat from start\nto end  (O(N))", "filter, return rows"]
    for i, s in enumerate(steps):
        box(ax, 0.1 + i * 2.4, 0.05, 2.1, 0.8, s, "#FDE7E7", 9)
        if i: arrow(ax, 0.1 + i * 2.4 - 0.3, 0.45, 0.1 + i * 2.4, 0.45)
    fig.savefig(os.path.join(OUT, "workflow.png"), dpi=170, bbox_inches="tight"); plt.close(fig)


def btree_example():
    fig, ax = canvas(10, 4)
    ax.text(5, 3.75, "A B-Tree with min degree t=2 (every node holds 1-3 keys); key -> file offset", ha="center", fontsize=11, fontweight="bold")
    box(ax, 4.0, 2.7, 2.0, 0.6, "[ 20 | 40 ]", C["api"], 11, True)
    kids = [(0.4, "[ 5 | 10 ]"), (3.0, "[ 25 | 30 ]"), (5.6, "[ 45 | 50 ]"), (8.0, "[ 60 | 70 | 80 ]")]
    for x, t in kids:
        box(ax, x, 1.2, 1.9 if "80" not in t else 1.8, 0.6, t, C["engine"], 10)
    for (x, _), px in zip(kids, [4.2, 4.8, 5.3, 5.8]):
        arrow(ax, px, 2.7, x + 0.95, 1.8)
    ax.text(5, 0.55, "Search 45: root -> 45 > 40 so go to 3rd child -> found.  2 node visits, not 11 key checks.\n"
                     "Each node's keys are kept sorted, so inside a node we binary-search.", ha="center", fontsize=9)
    fig.savefig(os.path.join(OUT, "btree_example.png"), dpi=170, bbox_inches="tight"); plt.close(fig)


def file_layout():
    fig, ax = canvas(11, 2.6)
    ax.text(5.5, 2.35, "users.dat  (append-only heap file)", ha="center", fontsize=11, fontweight="bold")
    parts = [("MINIDB01\nmagic", "#EEEEEE", 1.4), ("1 | len | [1,'Asha','Delhi']", C["engine"], 2.6), ("1 | len | [2,'Vik','Mumbai']", C["engine"], 2.6),
             ("0 | len | old version\n(tombstone)", "#FDE7E7", 2.0), ("1 | len | [2,'Vik','Pune']\n(new version)", C["engine"], 2.2)]
    x = 0.1
    for t, c, w in parts:
        box(ax, x, 0.9, w - 0.1, 0.9, t, c, 8); x += w
    ax.text(5.5, 0.35, "B-Tree index (users.idx on disk):  1 -> 8   |   2 -> offset of the NEWEST version     flag byte 1 = live, 0 = deleted",
            ha="center", fontsize=8.5)
    fig.savefig(os.path.join(OUT, "file_layout.png"), dpi=170, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    architecture(); workflow(); btree_example(); file_layout(); print("diagrams written to", OUT)
