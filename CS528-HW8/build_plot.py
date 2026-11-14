"""Create a black-and-white plot from the retained HW8 request and action records."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "report/evidence/20261114T032031Z"
rows = sorted([json.loads(x) for x in (RUN / "requests.jsonl").read_text().splitlines()], key=lambda x: x["sequence"])
events = [json.loads(x) for x in (RUN / "events.jsonl").read_text().splitlines()]
t0 = rows[0]["started_epoch"]
plt.rcParams.update({"font.family": "sans-serif", "font.size": 8, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.facecolor": "white"})
fig, ax = plt.subplots(figsize=(7, 2.65))
for zone, y, marker in [("us-central1-a", 2, "o"), ("us-central1-c", 1, "."), (None, 0, "x")]:
    points = [r for r in rows if (r["zone"] == zone if zone else not r["ok"])]
    ax.scatter([r["started_epoch"]-t0 for r in points], [y]*len(points),
               s=10 if zone else 16, marker=marker, c="black", linewidths=.6)
for e in events:
    stop = e["action"] == "stop"
    x = e["after_epoch" if stop else "before_epoch"] - t0
    ax.axvline(x, color="black", linestyle="--" if stop else ":", linewidth=.7)
    ax.text(x, 2.45, ("S" if stop else "R") + e["phase"].split("-")[1], ha="center", va="bottom", fontsize=7)
ax.set_yticks([0, 1, 2], ["Connection refused", "us-central1-c", "us-central1-a"])
ax.set_ylim(-.3, 2.75)
ax.set_xlim(-3, 467)
ax.set_xticks(range(0, 481, 60))
ax.set_xlabel("Seconds since the first request (one launch per second)")
ax.grid(axis="x", linestyle=":", color="0.7", linewidth=.4)
fig.tight_layout(pad=.7)
output = ROOT / "report/request_timeline.png"
fig.savefig(output, dpi=240)
plt.close(fig)
print(output)
