"""Plot observed live-demo spans and events on a common timeline."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# Offsets from estimated speech end, run cd0cf4c88e. MCP spans use server
# start/end events; ASR and TTS use the recorded HTTP start and first audio.
# These spans overlap and do not describe all time spent by the agent.
spans = [
    ('ASR request', 0.306, 2.168, '#8c70c7', '1.862 s'),
    ('Serve · MCP', 10.681, 10.726, '#319c85', '0.045 s'),
    ('Write HTML · MCP', 10.673, 11.399, '#319c85', '0.726 s'),
    ('Send link · Telegram', 13.949, 14.979, '#327db3', '1.030 s'),
    ('TTS request → first audio', 17.318, 17.468, '#5969b5', '0.150 s'),
]
fig, ax = plt.subplots(figsize=(11.8, 5.9), layout='constrained')
for row, (name, start, end, color, duration) in enumerate(spans):
    ax.barh(row, end - start, left=start, height=.48, color=color, zorder=3)
    ax.scatter([start, end], [row, row], marker='|', s=110, color=color, zorder=4)
    ax.text(end + .17, row, duration, va='center', fontsize=9, color='#263445')

# Milestones are points, not intervals or inferred LLM spans.
for row, timestamp, label, color in [
    (5, .359, '0.359 s · filler', '#558bc1'),
    (6, 2.152, '2.152 s · premature reply', '#cf752d'),
    (7, 2.172, '2.172 s · complete transcript', '#8061bb'),
    (8, 17.479, '17.479 s · later bot audio', '#5969b5'),
]:
    ax.scatter(timestamp, row, s=52, marker='D', color=color, zorder=4)
    if timestamp > 15:
        ax.annotate(label, (timestamp, row), xytext=(-9, 0), textcoords='offset points',
                    ha='right', va='center', fontsize=9, color=color)
    else:
        ax.annotate(label, (timestamp, row), xytext=(9, 0), textcoords='offset points',
                    ha='left', va='center', fontsize=9, color=color)

ax.set_yticks(range(9), [x[0] for x in spans] + ['Filler fired', 'Early reply', 'ASR final', 'Bot audio'])
ax.invert_yaxis()
ax.set_xlim(0, 19.2)
ax.set_xticks(range(0, 20, 2))
ax.set_xlabel('Seconds after estimated speech end')
ax.set_title('Live demo latency waterfall', loc='left', weight='bold', fontsize=15)
ax.grid(axis='x', alpha=.2)
ax.set_axisbelow(True)
for edge in ('top', 'right', 'left'):
    ax.spines[edge].set_visible(False)
ax.legend(handles=[Line2D([0], [0], color='#657b99', lw=5, label='Measured span'),
                   Line2D([0], [0], marker='D', color='w', markerfacecolor='#657b99',
                          markersize=7, label='Recorded event')],
          loc='upper right', frameon=False, fontsize=9)
fig.text(.01, -.035, 'Spans can overlap. Unshown gaps include unmeasured work; the early reply preceded the complete transcript.', fontsize=9)
out = Path(__file__).resolve().parent
fig.savefig(out / 'live-demo-latency.png', dpi=180, bbox_inches='tight')
fig.savefig(out / 'live-demo-latency.svg', bbox_inches='tight')
svg = out / 'live-demo-latency.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
