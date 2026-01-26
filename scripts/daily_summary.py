import os, json, datetime as dt, urllib.request
from zoneinfo import ZoneInfo

GH_TOKEN = os.environ["GH_TOKEN"]
GH_USERNAME = os.environ["GH_USERNAME"]
SUMMARY_REPO = os.environ["SUMMARY_REPO"]          # like "username/daily-github-summary"
TZ_NAME = os.environ.get("TZ_NAME", "America/Los_Angeles")

def gh_graphql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "daily-github-summary-bot",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]

def main():
    tz = ZoneInfo(TZ_NAME)
    now = dt.datetime.now(tz)
    day = now.date()

    start_local = dt.datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)

    query = """
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) {
        contributionsCollection(from:$from, to:$to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
          commitContributionsByRepository(maxRepositories: 100) {
            repository { nameWithOwner }
            contributions(first: 1) { totalCount }
          }
        }
      }
    }
    """

    data = gh_graphql(query, {
        "login": GH_USERNAME,
        "from": start_local.isoformat(),
        "to": end_local.isoformat(),
    })

    cc = data["user"]["contributionsCollection"]

    per_repo = {}
    for item in cc["commitContributionsByRepository"]:
        repo = item["repository"]["nameWithOwner"]
        count = item["contributions"]["totalCount"]
        per_repo[repo] = count

    total_commits = cc["totalCommitContributions"]
    total_prs = cc["totalPullRequestContributions"]
    total_issues = cc["totalIssueContributions"]
    total_reviews = cc["totalPullRequestReviewContributions"]

    summary_repo_commits = per_repo.get(SUMMARY_REPO, 0)
    real_commits = max(total_commits - summary_repo_commits, 0)
    real_total = real_commits + total_prs + total_issues + total_reviews

    lines = []
    lines.append(f"# Daily GitHub Summary — {day.isoformat()} ({TZ_NAME})")
    lines.append("")
    lines.append(f"Today, {GH_USERNAME} did:")
    lines.append("")
    if real_total == 0:
        lines.append("- Nothing was done.")
    else:
        lines.append(f"- Commits (excluding this repo): **{real_commits}**")
        lines.append(f"- Pull requests opened: **{total_prs}**")
        lines.append(f"- Issues opened: **{total_issues}**")
        lines.append(f"- Reviews: **{total_reviews}**")
        lines.append("")
        other_repos = [(r,c) for r,c in per_repo.items() if r != SUMMARY_REPO and c > 0]
        lines.append("### Commits by repo")
        if other_repos:
            for r,c in sorted(other_repos, key=lambda x: x[1], reverse=True):
                lines.append(f"- {r}: {c} commit{'s' if c != 1 else ''}")
        else:
            lines.append("- (No commits outside this repo.)")

    os.makedirs("summaries", exist_ok=True)
    out_path = os.path.join("summaries", f"{day.isoformat()}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
