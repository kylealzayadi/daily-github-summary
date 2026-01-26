import os
import json
import datetime as dt
import urllib.request
from zoneinfo import ZoneInfo

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GH_USERNAME = os.environ.get("GH_USERNAME")
SUMMARY_REPO = os.environ.get("SUMMARY_REPO") or ""
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
    unique_run_id = now.strftime('%Y%m%d-%H%M%S')
    print(f"[summary-bot][{unique_run_id}] Script started at {now.isoformat()} ({TZ_NAME})")

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
            contributions(first: 100) {
              totalCount
              nodes { occurredAt }
            }
          }
          pullRequestContributions(first:100) {
            totalCount
            nodes { occurredAt pullRequest { title url createdAt } }
          }
          issueContributions(first:100) {
            totalCount
            nodes { occurredAt issue { title url createdAt } }
          }
          pullRequestReviewContributions(first:100) {
            totalCount
            nodes { occurredAt pullRequestReview { body url submittedAt } }
          }
        }
        repositories(first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            nameWithOwner
            createdAt
            url
            isFork
          }
        }
      }
    }
    """

    print(f"[summary-bot][{unique_run_id}] Fetching GitHub data for {GH_USERNAME} from {start_local.isoformat()} to {end_local.isoformat()}")
    data = gh_graphql(query, {
        "login": GH_USERNAME,
        "from": start_local.isoformat(),
        "to": end_local.isoformat(),
    })
    # Find new repositories created on this day (not forks)
    new_repos = []
    for repo in data.get("user", {}).get("repositories", {}).get("nodes", []):
        created_at = repo.get("createdAt")
        is_fork = repo.get("isFork")
        if not is_fork and created_at:
            created_date = created_at[:10]
            if created_date == day.isoformat():
                new_repos.append({
                    "name": repo.get("nameWithOwner"),
                    "url": repo.get("url"),
                })
    print(f"[summary-bot][{unique_run_id}] GitHub data fetched successfully.")

    cc = data.get("user", {}).get("contributionsCollection", {})

    per_repo = {}
    commits_details = []
    for item in cc.get("commitContributionsByRepository", []):
        repo = item.get("repository", {}).get("nameWithOwner")
        contribs = item.get("contributions", {})
        count = contribs.get("totalCount", 0)
        if repo:
            per_repo[repo] = count
        for node in contribs.get("nodes", []):
            occ = node.get("occurredAt")
            if occ and repo:
                commits_details.append({"repo": repo, "when": occ})

    total_commits = cc.get("totalCommitContributions", 0)
    total_prs = cc.get("totalPullRequestContributions", 0)
    total_issues = cc.get("totalIssueContributions", 0)
    total_reviews = cc.get("totalPullRequestReviewContributions", 0)

    pr_details = []
    for n in cc.get("pullRequestContributions", {}).get("nodes", []):
        pr = n.get("pullRequest") or {}
        pr_details.append({"title": pr.get("title"), "url": pr.get("url"), "when": n.get("occurredAt")})

    issue_details = []
    for n in cc.get("issueContributions", {}).get("nodes", []):
        isu = n.get("issue") or {}
        issue_details.append({"title": isu.get("title"), "url": isu.get("url"), "when": n.get("occurredAt")})

    review_details = []
    for n in cc.get("pullRequestReviewContributions", {}).get("nodes", []):
        rev = n.get("pullRequestReview") or {}
        review_details.append({"body": (rev.get("body") or '').strip()[:200], "url": rev.get("url"), "when": n.get("occurredAt")})

    summary_repo_commits = per_repo.get(SUMMARY_REPO, 0)
    real_commits = max(total_commits - summary_repo_commits, 0)
    real_total = real_commits + total_prs + total_issues + total_reviews

    # Format run time with timezone abbreviation (e.g., PST/PDT)
    run_time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z (Pacific Time)')
    lines = []
    lines.append(f"# Daily GitHub Summary - {day.isoformat()} ({TZ_NAME})")
    lines.append(f"**Run at:** {run_time_str}")
    lines.append("")
    lines.append(f"Today, {GH_USERNAME} did:")
    lines.append("")
    if real_total == 0 and not new_repos:
      lines.append("- Nothing was done.")
    else:
      if new_repos:
        lines.append(f"- Repositories created: **{len(new_repos)}**")
        for repo in new_repos:
          lines.append(f"    - [{repo['name']}]({repo['url']})")
      lines.append(f"- Commits (excluding this repo): **{real_commits}**")
      lines.append(f"- Pull requests opened: **{total_prs}**")
      lines.append(f"- Issues opened: **{total_issues}**")
      lines.append(f"- Reviews: **{total_reviews}**")
      lines.append("")
      other_repos = [(r, c) for r, c in per_repo.items() if r != SUMMARY_REPO and c > 0]
      lines.append("### Commits by repo")
      if other_repos:
        for r, c in sorted(other_repos, key=lambda x: x[1], reverse=True):
          lines.append(f"- {r}: {c} commit{'s' if c != 1 else ''}")
      else:
        lines.append("- (No commits outside this repo.)")

    os.makedirs("summaries", exist_ok=True)
    # Use a unique filename for each run: summaries/YYYY-MM-DD-HHMMSS.md
    out_path = os.path.join("summaries", f"{day.isoformat()}-{now.strftime('%H%M%S')}.md")
    print(f"[summary-bot][{unique_run_id}] Writing summary to {out_path}")
    summary_content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
      f.write(summary_content)
    print(f"[summary-bot][{unique_run_id}] Summary written successfully. Preview:")
    print("\n".join(lines[:10]) + ("\n..." if len(lines) > 10 else ""))

    # Update README.md with the latest summary
    readme_path = "README.md"
    if os.path.exists(readme_path):
      with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()
      start_marker = "<!-- summary-bot-latest-start -->"
      end_marker = "<!-- summary-bot-latest-end -->"
      if start_marker in readme and end_marker in readme:
        before = readme.split(start_marker)[0]
        after = readme.split(end_marker)[1]
        new_readme = before + start_marker + "\n" + summary_content + "\n" + end_marker + after
        with open(readme_path, "w", encoding="utf-8") as f:
          f.write(new_readme)


if __name__ == "__main__":
    main()
