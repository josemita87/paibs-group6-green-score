"""Render the README figures from results/metrics.json.

Standard library only, so it adds no dependency to the demo. Every number drawn
comes from the metrics file written by `prototype.py train`; nothing is typed in
by hand. Run after training:

    python make_figures.py
"""
import json
import pathlib

RESULTS = pathlib.Path(__file__).parent / 'results'
FIGURES = RESULTS / 'figures'

LIGHT = {'baseline': '#2a78d6', 'model': '#eb6834', 'ink': '#3c3c3a',
         'muted': '#6b6a66', 'rule': '#d9d8d3'}
DARK = {'baseline': '#3987e5', 'model': '#d95926', 'ink': '#e6e5e1',
        'muted': '#a3a29b', 'rule': '#3a3a38'}

ROW = 30
BAR = 14
LABEL_W = 232
PAD = 16


def end_rounded(x, y, width, height, radius=4):
    """A bar anchored at the baseline with only its data end rounded."""
    radius = min(radius, max(width, 0))
    if width <= radius:
        return f'M{x},{y}h{width}v{height}h{-width}z'
    return (f'M{x},{y}h{width - radius}a{radius},{radius} 0 0 1 {radius},{radius}'
            f'v{height - 2 * radius}a{radius},{radius} 0 0 1 {-radius},{radius}'
            f'h{-(width - radius)}z')


def panel(rows, x0, y0, plot_w, axis_max, fmt, colors, steps=5, tick_fmt=None):
    """One single-measure bar panel. rows: (label, value, is_model)."""
    out = []
    tick_fmt = tick_fmt or fmt
    for step in range(0, steps + 1):
        tick = axis_max * step / steps
        tx = x0 + plot_w * step / steps
        out.append(f'<line x1="{tx:.1f}" y1="{y0 - 6}" x2="{tx:.1f}" '
                   f'y2="{y0 + ROW * len(rows) - 8}" stroke="{colors["rule"]}" stroke-width="1"/>')
        out.append(f'<text x="{tx:.1f}" y="{y0 - 12}" fill="{colors["muted"]}" '
                   f'font-size="11" text-anchor="middle">{tick_fmt(tick)}</text>')
    for index, (label, value, is_model) in enumerate(rows):
        y = y0 + index * ROW
        width = plot_w * value / axis_max if axis_max else 0
        fill = colors['model'] if is_model else colors['baseline']
        out.append(f'<text x="{x0 - 10}" y="{y + BAR - 3}" fill="{colors["ink"]}" '
                   f'font-size="12" text-anchor="end">{label}</text>')
        out.append(f'<path d="{end_rounded(x0, y, width, BAR)}" fill="{fill}"/>')
        out.append(f'<text x="{x0 + width + 8:.1f}" y="{y + BAR - 3}" '
                   f'fill="{colors["muted"]}" font-size="12">{fmt(value)}</text>')
    return out


def legend(x, y, colors, items):
    out = []
    for label, key in items:
        out.append(f'<rect x="{x}" y="{y - 8}" width="10" height="10" rx="2" fill="{colors[key]}"/>')
        out.append(f'<text x="{x + 16}" y="{y}" fill="{colors["muted"]}" font-size="11">{label}</text>')
        x += 20 + 7 * len(label)
    return out


def svg(width, height, body, colors):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            'viewBox="0 0 {w} {h}" font-family="-apple-system,BlinkMacSystemFont,'
            'Segoe UI,Helvetica,Arial,sans-serif" role="img">{b}</svg>').format(
                w=width, h=height, b=''.join(body))


def regression_figure(metrics, colors):
    rows = [('Global median', metrics['global_median_mae'], False),
            ('Category median baseline', metrics['category_median_mae'], False),
            ('Ingredients only', metrics['ingredient_only_mae'], True),
            ('Ingredients + categories', metrics['combined_model_mae'], True),
            ('Combined, categories masked', metrics['combined_categories_masked_mae'], True)]
    axis_max = 25.0
    plot_w = 760 - LABEL_W - 70
    body = [f'<text x="{PAD}" y="22" fill="{colors["ink"]}" font-size="14" '
            f'font-weight="600">Score regression: mean absolute error, lower is better</text>',
            f'<text x="{PAD}" y="40" fill="{colors["muted"]}" font-size="11">'
            f'Held-out test set, {metrics["test_n"]} labelled products. '
            f'No model beats the category median.</text>']
    body += panel(rows, LABEL_W, 78, plot_w, axis_max, lambda v: f'{v:.1f}', colors,
                  tick_fmt=lambda v: f'{v:.0f}')
    body += legend(LABEL_W, 78 + ROW * len(rows) + 18, colors,
                   [('Baseline', 'baseline'), ('Trained model', 'model')])
    return svg(760, 78 + ROW * len(rows) + 34, body, colors)


def category_figure(metrics, colors):
    supported = [('Majority class', metrics['category_majority_accuracy'], False),
                 ('Three-rule diagnostic', metrics['category_three_rule_accuracy_supported'], False),
                 ('Trained classifier', metrics['category_top1_accuracy'], True)]
    overall = [('Three-rule diagnostic', metrics['category_three_rule_accuracy_all'], False),
               ('Trained classifier', metrics['category_top1_accuracy_all_test'], True)]
    plot_w = 760 - LABEL_W - 70
    pct = lambda v: f'{v * 100:.1f}%'
    tick = lambda v: f'{v * 100:.0f}%'
    body = [f'<text x="{PAD}" y="22" fill="{colors["ink"]}" font-size="14" '
            f'font-weight="600">Category suggestion: top-1 accuracy</text>',
            f'<text x="{PAD}" y="40" fill="{colors["muted"]}" font-size="11">'
            f'Supported classes cover {metrics["category_test_supported_fraction"] * 100:.1f}% '
            f'of test labels. Unsupported classes count as wrong.</text>',
            f'<text x="{PAD}" y="76" fill="{colors["ink"]}" font-size="12" font-weight="600">'
            f'Supported labels ({metrics["category_test_supported_n"]} records)</text>']
    body += panel(supported, LABEL_W, 96, plot_w, 1.0, pct, colors, steps=4, tick_fmt=tick)
    second = 96 + ROW * len(supported) + 28
    body.append(f'<text x="{PAD}" y="{second - 14}" fill="{colors["ink"]}" font-size="12" '
                f'font-weight="600">All test labels ({metrics["category_test_all_n"]} records)</text>')
    body += panel(overall, LABEL_W, second + 10, plot_w, 1.0, pct, colors, steps=4, tick_fmt=tick)
    bottom = second + 10 + ROW * len(overall) + 18
    body += legend(LABEL_W, bottom, colors, [('Baseline', 'baseline'), ('Trained model', 'model')])
    return svg(760, bottom + 16, body, colors)


def main():
    metrics = json.loads((RESULTS / 'metrics.json').read_text())
    FIGURES.mkdir(exist_ok=True)
    for name, build in (('regression_mae', regression_figure), ('category_accuracy', category_figure)):
        for mode, colors in (('light', LIGHT), ('dark', DARK)):
            path = FIGURES / f'{name}_{mode}.svg'
            path.write_text(build(metrics, colors))
            print('wrote', path.relative_to(RESULTS.parent))


if __name__ == '__main__':
    main()
