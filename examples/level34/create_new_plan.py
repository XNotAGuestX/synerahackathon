"""Regenerate the tiny, dimensioned CC0 floor-plan raster used in the import demo."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc


OUTPUT = Path(__file__).with_name("new-plan.png")


def draw(output: Path, level: int = 0, elevation_m: float = 0.0) -> None:
    fig, ax = plt.subplots(figsize=(12, 8.5), dpi=100)
    ax.set_xlim(0, 1200)
    ax.set_ylim(850, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("white")

    left, split, right = 200, 600, 1000
    top, bottom = 230, 550
    wall, thin = 9, 3

    ax.text(600, 82, f"LEVEL {level}   ·   Floor {level}   ·   elevation {elevation_m:g} m", ha="center", va="center",
            fontsize=22, weight="bold", color="#182433")
    ax.text(600, 125, "All doors step-free; width 1.2 m", ha="center", va="center",
            fontsize=17, color="#182433")

    # Outer walls: leave one measured entrance gap in the west wall.
    ax.plot([left, right], [top, top], color="#17212b", lw=wall, solid_capstyle="butt")
    ax.plot([left, right], [bottom, bottom], color="#17212b", lw=wall, solid_capstyle="butt")
    ax.plot([right, right], [top, bottom], color="#17212b", lw=wall, solid_capstyle="butt")
    entrance_y0, entrance_y1 = 382, 478  # 96 px at 80 px/m = 1.2 m
    ax.plot([left, left], [top, entrance_y0], color="#17212b", lw=wall, solid_capstyle="butt")
    ax.plot([left, left], [entrance_y1, bottom], color="#17212b", lw=wall, solid_capstyle="butt")

    # Interior wall and a 96 px clear opening (1.2 m at the indicated plan scale).
    door_y0, door_y1 = 342, 438
    ax.plot([split, split], [top, door_y0], color="#17212b", lw=wall, solid_capstyle="butt")
    ax.plot([split, split], [door_y1, bottom], color="#17212b", lw=wall, solid_capstyle="butt")

    # Door leaves and swing arcs, drawn inside each clear opening.
    ax.plot([left, left + 96], [entrance_y0, entrance_y0], color="#305b78", lw=thin)
    ax.add_patch(Arc((left, entrance_y0), 192, 192, theta1=0, theta2=90, color="#305b78", lw=thin))
    ax.plot([split, split + 96], [door_y0, door_y0], color="#305b78", lw=thin)
    ax.add_patch(Arc((split, door_y0), 192, 192, theta1=0, theta2=90, color="#305b78", lw=thin))

    ax.text(400, 382, "LOBBY", ha="center", va="center", fontsize=24, weight="bold", color="#17212b")
    ax.text(400, 421, "Space 1", ha="center", va="center", fontsize=15, color="#526272")
    ax.text(800, 382, "LAB", ha="center", va="center", fontsize=24, weight="bold", color="#17212b")
    ax.text(800, 421, "Space 2", ha="center", va="center", fontsize=15, color="#526272")
    ax.text(146, 430, "ENTRANCE", ha="center", va="center", rotation=90, fontsize=14, weight="bold",
            color="#305b78")
    ax.text(654, 320, "1.2 m door", ha="left", va="bottom", fontsize=13, color="#305b78")

    # Dimension lines terminate at the physical exterior wall endpoints.
    dim_y = 650
    ax.plot([left, left], [bottom + 8, dim_y + 12], color="#657482", lw=thin)
    ax.plot([right, right], [bottom + 8, dim_y + 12], color="#657482", lw=thin)
    ax.annotate("", xy=(right, dim_y), xytext=(left, dim_y),
                arrowprops={"arrowstyle": "<->", "lw": 2.5, "color": "#263746"})
    ax.text(600, dim_y - 15, "10 m", ha="center", va="bottom", fontsize=21, weight="bold", color="#17212b",
            bbox={"fc": "white", "ec": "none", "pad": 3})

    dim_x = 1080
    ax.plot([right + 8, dim_x + 10], [top, top], color="#657482", lw=thin)
    ax.plot([right + 8, dim_x + 10], [bottom, bottom], color="#657482", lw=thin)
    ax.annotate("", xy=(dim_x, bottom), xytext=(dim_x, top),
                arrowprops={"arrowstyle": "<->", "lw": 2.5, "color": "#263746"})
    ax.text(dim_x + 30, 390, "4 m", ha="left", va="center", rotation=90, fontsize=21, weight="bold",
            color="#17212b", bbox={"fc": "white", "ec": "none", "pad": 3})

    ax.text(600, 780, "Source: generated for this demo · CC0 1.0", ha="center", va="center",
            fontsize=12, color="#526272")
    fig.savefig(output, dpi=100, facecolor="white")
    plt.close(fig)


def main() -> None:
    draw(OUTPUT)


if __name__ == "__main__":
    main()
