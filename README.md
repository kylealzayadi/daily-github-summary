# Daily WHOOP Summary

This repository automatically generates and commits a daily summary of WHOOP health data (recovery, sleep, strain, workouts).

## Latest Summary

<!-- summary-bot-latest-start -->
Waiting for first WHOOP summary...
<!-- summary-bot-latest-end -->

## How it works
- A GitHub Actions workflow runs up to 5 times daily at randomized intervals (1-5 commits per day, determined by date seed).
- Each active run fetches WHOOP data via the API and generates a Markdown summary.
- The summary is saved in the `summaries/` folder and also shown above.

## Setup
Add these secrets to your repository:
- `WHOOP_CLIENT_ID` — your WHOOP developer app client ID
- `WHOOP_CLIENT_SECRET` — your WHOOP developer app client secret
- `WHOOP_REFRESH_TOKEN` — obtained from the initial OAuth flow
- `GH_PAT` — personal access token with `repo` scope (for rotating refresh token)

## All Summaries
See the `summaries/` folder for a complete history of daily summaries.
