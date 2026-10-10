"""Markdown run report: source health plus the top events, for the Actions summary."""
import json
import sys

data = json.load(open(sys.argv[1]))
print(f"## {len(data['events'])} events · generated {data['generated']} · AI {'on' if data['ai'] else 'off'}\n")
print("| Source | Events | Status |\n|---|---|---|")
for s in data["sources"]:
    print(f"| {s['label']} | {s['count']} | {'OK' if s['ok'] else (s['error'] or '')[:120].replace('|', '/')} |")
print("\n### Top 30 by score\n\n| Score | When | Event | Why | Source |\n|---|---|---|---|---|")
for e in sorted(data["events"], key=lambda e: -e["score"])[:30]:
    print(f"| {e['score']} | {e['start'][:16].replace('T', ' ')} | [{e['title'][:70]}]({e['source_url']}) | {e['why'][:60]} | {e['source']} |")
