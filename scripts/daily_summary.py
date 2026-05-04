import os
import sys
import json
import random
import hashlib
import datetime as dt
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo

WHOOP_CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID")
WHOOP_CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET")
WHOOP_REFRESH_TOKEN = os.environ.get("WHOOP_REFRESH_TOKEN")
GH_PAT = os.environ.get("GH_PAT")
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")
TZ_NAME = os.environ.get("TZ_NAME", "America/Los_Angeles")
RUN_SLOT = int(os.environ.get("RUN_SLOT", "1"))


def should_run_today(day: dt.date, slot: int) -> bool:
    seed = int(hashlib.sha256(day.isoformat().encode()).hexdigest(), 16)
    rng = random.Random(seed)
    num_commits_today = rng.randint(1, 5)
    return slot <= num_commits_today


def refresh_whoop_token() -> tuple[str, str]:
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": WHOOP_REFRESH_TOKEN,
        "client_id": WHOOP_CLIENT_ID,
        "client_secret": WHOOP_CLIENT_SECRET,
        "scope": "offline",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.prod.whoop.com/oauth/oauth2/token",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "daily-whoop-summary-bot",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["access_token"], payload["refresh_token"]


def update_github_secret(secret_name: str, secret_value: str):
    from base64 import b64encode
    try:
        from nacl import encoding, public
    except ImportError:
        os.system("pip install pynacl -q")
        from nacl import encoding, public

    key_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    req = urllib.request.Request(key_url, headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        key_data = json.loads(resp.read().decode("utf-8"))

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    encrypted_value = b64encode(encrypted).decode("utf-8")

    secret_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{secret_name}"
    put_data = json.dumps({
        "encrypted_value": encrypted_value,
        "key_id": key_data["key_id"],
    }).encode("utf-8")
    req = urllib.request.Request(secret_url, data=put_data, headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }, method="PUT")
    with urllib.request.urlopen(req) as resp:
        pass


def whoop_get(endpoint: str, access_token: str, params: dict = None) -> dict:
    url = f"https://api.prod.whoop.com/developer{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "daily-whoop-summary-bot",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ms_to_hours_min(ms: int) -> str:
    total_min = ms // 60000
    hours = total_min // 60
    mins = total_min % 60
    return f"{hours}h {mins}m"


def main():
    tz = ZoneInfo(TZ_NAME)
    now = dt.datetime.now(tz)
    day = now.date()
    unique_run_id = now.strftime('%Y%m%d-%H%M%S')
    print(f"[summary-bot][{unique_run_id}] Script started at {now.isoformat()} ({TZ_NAME})")
    print(f"[summary-bot][{unique_run_id}] Run slot: {RUN_SLOT}")

    if not should_run_today(day, RUN_SLOT):
        print(f"[summary-bot][{unique_run_id}] Slot {RUN_SLOT} not active today. Skipping.")
        return

    print(f"[summary-bot][{unique_run_id}] Slot {RUN_SLOT} is active today. Proceeding.")

    # Refresh WHOOP token
    print(f"[summary-bot][{unique_run_id}] Refreshing WHOOP token...")
    access_token, new_refresh_token = refresh_whoop_token()
    print(f"[summary-bot][{unique_run_id}] Token refreshed successfully.")

    # Update the refresh token secret for next run
    if GH_PAT and GH_REPO:
        print(f"[summary-bot][{unique_run_id}] Updating WHOOP_REFRESH_TOKEN secret...")
        update_github_secret("WHOOP_REFRESH_TOKEN", new_refresh_token)
        print(f"[summary-bot][{unique_run_id}] Secret updated.")

    # Fetch today's WHOOP data
    start_local = dt.datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)
    start_iso = start_local.isoformat()
    end_iso = end_local.isoformat()

    print(f"[summary-bot][{unique_run_id}] Fetching WHOOP data from {start_iso} to {end_iso}")

    recovery_data = whoop_get("/v2/recovery", access_token, {"start": start_iso, "end": end_iso})
    sleep_data = whoop_get("/v2/activity/sleep", access_token, {"start": start_iso, "end": end_iso})
    cycle_data = whoop_get("/v2/cycle", access_token, {"start": start_iso, "end": end_iso})
    workout_data = whoop_get("/v2/activity/workout", access_token, {"start": start_iso, "end": end_iso})

    print(f"[summary-bot][{unique_run_id}] WHOOP data fetched.")

    # Build summary
    run_time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z (Pacific Time)')
    lines = []
    lines.append(f"# Daily WHOOP Summary - {day.isoformat()} ({TZ_NAME})")
    lines.append(f"**Run at:** {run_time_str}")
    lines.append("")

    # Recovery
    lines.append("## Recovery")
    recovery_records = recovery_data.get("records", [])
    if recovery_records:
        rec = recovery_records[0]
        score = rec.get("score", {})
        if score and rec.get("score_state") == "SCORED":
            lines.append(f"- **Recovery Score:** {score.get('recovery_score', 'N/A')}%")
            lines.append(f"- **HRV (RMSSD):** {score.get('hrv_rmssd_milli', 'N/A')} ms")
            lines.append(f"- **Resting Heart Rate:** {score.get('resting_heart_rate', 'N/A')} bpm")
            spo2 = score.get('spo2_percentage')
            if spo2:
                lines.append(f"- **SpO2:** {spo2}%")
            skin_temp = score.get('skin_temp_celsius')
            if skin_temp:
                lines.append(f"- **Skin Temp:** {skin_temp}°C")
        else:
            lines.append("- Recovery not yet scored.")
    else:
        lines.append("- No recovery data available.")
    lines.append("")

    # Sleep
    lines.append("## Sleep")
    sleep_records = sleep_data.get("records", [])
    sleeps = [s for s in sleep_records if not s.get("nap", False)]
    if sleeps:
        slp = sleeps[0]
        score = slp.get("score", {})
        if score and slp.get("score_state") == "SCORED":
            stage = score.get("stage_summary", {})
            total_sleep = (stage.get("total_in_bed_time_milli", 0)
                          - stage.get("total_awake_time_milli", 0))
            lines.append(f"- **Sleep Performance:** {score.get('sleep_performance_percentage', 'N/A')}%")
            lines.append(f"- **Sleep Duration:** {ms_to_hours_min(total_sleep)}")
            lines.append(f"- **Time in Bed:** {ms_to_hours_min(stage.get('total_in_bed_time_milli', 0))}")
            lines.append(f"- **Sleep Efficiency:** {score.get('sleep_efficiency_percentage', 'N/A')}%")
            lines.append(f"- **Sleep Consistency:** {score.get('sleep_consistency_percentage', 'N/A')}%")
            lines.append(f"- **Respiratory Rate:** {score.get('respiratory_rate', 'N/A')} breaths/min")
            lines.append(f"- **Disturbances:** {stage.get('disturbance_count', 'N/A')}")
            lines.append("")
            lines.append("### Sleep Stages")
            lines.append(f"- Light: {ms_to_hours_min(stage.get('total_light_sleep_time_milli', 0))}")
            lines.append(f"- Deep (SWS): {ms_to_hours_min(stage.get('total_slow_wave_sleep_time_milli', 0))}")
            lines.append(f"- REM: {ms_to_hours_min(stage.get('total_rem_sleep_time_milli', 0))}")
            lines.append(f"- Awake: {ms_to_hours_min(stage.get('total_awake_time_milli', 0))}")
        else:
            lines.append("- Sleep not yet scored.")
    else:
        lines.append("- No sleep data available.")
    lines.append("")

    # Strain / Cycles
    lines.append("## Strain")
    cycle_records = cycle_data.get("records", [])
    if cycle_records:
        cyc = cycle_records[0]
        score = cyc.get("score", {})
        if score and cyc.get("score_state") == "SCORED":
            lines.append(f"- **Day Strain:** {score.get('strain', 'N/A')}")
            lines.append(f"- **Calories:** {round(score.get('kilojoule', 0) * 0.239006, 1)} kcal")
            lines.append(f"- **Average Heart Rate:** {score.get('average_heart_rate', 'N/A')} bpm")
            lines.append(f"- **Max Heart Rate:** {score.get('max_heart_rate', 'N/A')} bpm")
        else:
            lines.append("- Strain not yet scored.")
    else:
        lines.append("- No strain data available.")
    lines.append("")

    # Workouts
    lines.append("## Workouts")
    workout_records = workout_data.get("records", [])
    if workout_records:
        for i, w in enumerate(workout_records, 1):
            score = w.get("score", {})
            sport = w.get("sport_name", "Activity")
            start_time = w.get("start", "")
            end_time = w.get("end", "")
            if start_time and end_time:
                s = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                e = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                duration = e - s
                dur_str = ms_to_hours_min(int(duration.total_seconds() * 1000))
            else:
                dur_str = "N/A"
            lines.append(f"### {i}. {sport}")
            lines.append(f"- Duration: {dur_str}")
            if score:
                lines.append(f"- Strain: {score.get('strain', 'N/A')}")
                lines.append(f"- Avg HR: {score.get('average_heart_rate', 'N/A')} bpm")
                lines.append(f"- Max HR: {score.get('max_heart_rate', 'N/A')} bpm")
                lines.append(f"- Calories: {round(score.get('kilojoule', 0) * 0.239006, 1)} kcal")
                dist = score.get('distance_meter')
                if dist:
                    lines.append(f"- Distance: {round(dist / 1000, 2)} km")
            lines.append("")
    else:
        lines.append("- No workouts recorded today.")
    lines.append("")

    # Write summary
    os.makedirs("summaries", exist_ok=True)
    out_path = os.path.join("summaries", f"{day.isoformat()}-{now.strftime('%H%M%S')}.md")
    print(f"[summary-bot][{unique_run_id}] Writing summary to {out_path}")
    summary_content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary_content)
    print(f"[summary-bot][{unique_run_id}] Summary written. Preview:")
    print("\n".join(lines[:15]) + ("\n..." if len(lines) > 15 else ""))

    # Update README.md
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

    # Signal to the workflow that we should commit
    with open("__should_commit__", "w") as f:
        f.write("yes")


if __name__ == "__main__":
    main()
