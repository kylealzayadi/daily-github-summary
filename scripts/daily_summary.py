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
                        contributions(first: 100) {
                            totalCount
                            nodes {
                                occurredAt
                                # commit details may be present depending on contribution type
                                commitCount: __typename
                                # some contribution nodes include commit (GitHub may omit raw commit object)
                                # we'll attempt to access any available fields defensively below
                            }
                        }
                    }
                    pullRequestContributions(first:100) {
                        totalCount
                        nodes {
                            occurredAt
                            pullRequest { title url createdAt }
                        }
                    }
                    issueContributions(first:100) {
                        totalCount
                        nodes {
                            occurredAt
                            issue { title url createdAt }
                        }
                    }
                    pullRequestReviewContributions(first:100) {
                        totalCount
                        nodes {
                            occurredAt
                            pullRequestReview { body url submittedAt }
                        }
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
        commits_details = []
        for item in cc.get("commitContributionsByRepository", []):
                repo = item["repository"]["nameWithOwner"]
                contribs = item.get("contributions", {})
                count = contribs.get("totalCount", 0)
                per_repo[repo] = count
                # collect any nodes' occurredAt for basic timestamps
                for node in contribs.get("nodes", []):
                        occ = node.get("occurredAt")
                        if occ:
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
