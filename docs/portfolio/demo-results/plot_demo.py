"""Plot recorded single-task milestones; run with matplotlib installed."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# From run cd0cf4c88e, relative to the interrupted request's final estimated
# speech end at 05:34:26.505. Rounded; see report for event definitions.
events = [
    ('Short filler fired', 0.359, '#64a8ea'),
    ('Premature reply starts', 2.152, '#e69446'),
    ('Full ASR transcript', 2.172, '#8c70c7'),
    ('Serve tool completed', 10.726, '#3a9f88'),
    ('HTML write completed', 11.399, '#3a9f88'),
    ('Telegram accepted link', 14.979, '#2d7fbb'),
    ('Next bot audio starts', 17.479, '#5d6ab7'),
]
fig, ax = plt.subplots(figsize=(10, 5.1), layout='constrained')
for i, (name, seconds, color) in enumerate(events):
    ax.barh(i, seconds, height=.53, color=color)
    ax.text(seconds + .25, i, f'{seconds:.3f} s', va='center', fontsize=10)
ax.set_yticks(range(len(events)), [e[0] for e in events])
ax.invert_yaxis()
ax.set_xlim(0, 20)
ax.set_xlabel('Seconds after estimated speech end')
ax.set_title('Live demo: interrupted dashboard request', loc='left', weight='bold')
ax.grid(axis='x', alpha=.2)
ax.set_axisbelow(True)
for edge in ('top', 'right', 'left'):
    ax.spines[edge].set_visible(False)
fig.text(.01, -.035, 'Single event timeline, not additive stage latencies. The 2.152 s reply preceded the full transcript.', fontsize=9)
out = Path(__file__).resolve().parent
fig.savefig(out / 'live-demo-latency.png', dpi=180, bbox_inches='tight')
fig.savefig(out / 'live-demo-latency.svg', bbox_inches='tight')
svg = out / 'live-demo-latency.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
