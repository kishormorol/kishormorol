"""Render the GitHub stats cards shown in the profile README.

Runs daily from .github/workflows/stats.yml. Queries the GraphQL API with
GITHUB_TOKEN and writes light and dark SVGs into assets/. Standard library only.
"""

import datetime as dt
import html
import json
import os
import pathlib
import urllib.request

USER = os.environ.get("STATS_USER", "kishormorol")
TOKEN = os.environ["GITHUB_TOKEN"]
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Markup, notebooks and data files swamp the byte counts without saying much
# about the code itself. Smalltalk is a misdetected data file in an old repo.
SKIP_LANGS = {
    "HTML", "CSS", "Jupyter Notebook", "TeX", "BibTeX Style", "Procfile",
    "Makefile", "Dockerfile", "Smalltalk",
}

THEMES = {
    "light": dict(bg="#ffffff", border="#d0d7de", text="#1f2328", muted="#59636e", track="#eff2f5"),
    "dark": dict(bg="#0d1117", border="#30363d", text="#e6edf3", muted="#9198a1", track="#21262d"),
}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def collect():
    profile = gql(
        """query($u:String!){user(login:$u){
          followers{totalCount}
          contributionsCollection{contributionYears}
          repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,ISSUE,REPOSITORY]){totalCount}
        }}""",
        u=USER,
    )["user"]

    totals = dict(contributions=0, commits=0, prs=0, issues=0)
    days = {}
    for year in profile["contributionsCollection"]["contributionYears"]:
        c = gql(
            """query($u:String!,$from:DateTime!,$to:DateTime!){user(login:$u){
              contributionsCollection(from:$from,to:$to){
                totalCommitContributions totalPullRequestContributions totalIssueContributions
                contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}
              }}}""",
            u=USER, **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        totals["contributions"] += c["contributionCalendar"]["totalContributions"]
        totals["commits"] += c["totalCommitContributions"]
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        for week in c["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]

    stars, langs, cursor = 0, {}, None
    while True:
        page = gql(
            """query($u:String!,$after:String){user(login:$u){
              repositories(ownerAffiliations:OWNER,privacy:PUBLIC,isFork:false,first:100,after:$after){
                pageInfo{hasNextPage endCursor}
                nodes{stargazerCount languages(first:20){edges{size node{name color}}}}
              }}}""",
            u=USER, after=cursor,
        )["user"]["repositories"]
        for repo in page["nodes"]:
            stars += repo["stargazerCount"]
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                if name in SKIP_LANGS:
                    continue
                size, _ = langs.get(name, (0, None))
                langs[name] = (size + edge["size"], edge["node"]["color"] or "#8b949e")
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    current, longest = streaks(days)
    return dict(
        totals,
        stars=stars,
        followers=profile["followers"]["totalCount"],
        contributed=profile["repositoriesContributedTo"]["totalCount"],
        current=current,
        longest=longest,
        langs=sorted(langs.items(), key=lambda kv: -kv[1][0]),
    )


def streaks(days):
    """Current and longest runs of days with at least one contribution.

    Today not having a contribution yet does not break the current streak.
    """
    today = dt.date.today()
    dates = sorted(d for d in days if dt.date.fromisoformat(d) <= today)
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    current = 0
    day = today if days.get(today.isoformat()) else today - dt.timedelta(days=1)
    while days.get(day.isoformat()):
        current += 1
        day -= dt.timedelta(days=1)
    return current, longest


def stats_svg(s, t):
    cells = [
        ("Total contributions", f"{s['contributions']:,}"),
        ("Public commits", f"{s['commits']:,}"),
        ("Public pull requests", f"{s['prs']:,}"),
        ("Issues", f"{s['issues']:,}"),
        ("Contributed to", f"{s['contributed']:,} repos"),
        ("Stars earned", f"{s['stars']:,}"),
        ("Followers", f"{s['followers']:,}"),
        ("Current streak", f"{s['current']:,} days"),
        ("Longest streak", f"{s['longest']:,} days"),
    ]
    w, h, col_w, row_h, top = 800, 270, 250, 62, 72
    parts = [
        f'<text x="25" y="42" font-size="18" font-weight="600" fill="{t["text"]}">GitHub stats</text>',
    ]
    for i, (label, value) in enumerate(cells):
        x, y = 25 + (i % 3) * col_w, top + (i // 3) * row_h
        parts.append(f'<text x="{x}" y="{y + 26}" font-size="24" font-weight="600" fill="{t["text"]}">{value}</text>')
        parts.append(f'<text x="{x}" y="{y + 46}" font-size="13" fill="{t["muted"]}">{label}</text>')
    return card(w, h, t, parts)


def langs_svg(s, t, top_n=6):
    langs = s["langs"][:top_n]
    total = sum(size for _, (size, _) in langs) or 1
    w, h, bar_x, bar_w, bar_y = 800, 150, 25, 750, 62
    parts = [
        f'<text x="25" y="42" font-size="18" font-weight="600" fill="{t["text"]}">Top languages</text>',
        f'<clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5"/></clipPath>',
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5" fill="{t["track"]}"/>',
        '<g clip-path="url(#bar)">',
    ]
    x = bar_x
    for _, (size, color) in langs:
        seg = bar_w * size / total
        parts.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{seg:.2f}" height="10" fill="{color}"/>')
        x += seg
    parts.append("</g>")
    for i, (name, (size, color)) in enumerate(langs):
        lx, ly = 25 + (i % 3) * 250, 104 + (i // 3) * 26
        parts.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>')
        parts.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="13" fill="{t["text"]}">{html.escape(name)} '
            f'<tspan fill="{t["muted"]}">{100 * size / total:.1f}%</tspan></text>'
        )
    return card(w, h, t, parts)


def card(w, h, t, parts):
    body = "\n  ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="{FONT}">\n'
        f'  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="8" fill="{t["bg"]}" stroke="{t["border"]}"/>\n'
        f"  {body}\n</svg>\n"
    )


def main():
    s = collect()
    OUT.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT / f"stats-{name}.svg").write_text(stats_svg(s, theme))
        (OUT / f"langs-{name}.svg").write_text(langs_svg(s, theme))
    print(json.dumps({k: v for k, v in s.items() if k != "langs"}))


if __name__ == "__main__":
    main()
