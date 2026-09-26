"""SHION CORE v0.3: scheduled research -> reflection -> Drive appData memory.
No credentials are stored in this repository. Designed for GitHub Actions.
"""
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

import requests
from openai import OpenAI

DRIVE_NAME = "shion-core-memory.json"  # Matches v0.2 browser client.
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.appdata"

def env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret/variable: {name}")
    return value

def token():
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env("GOOGLE_CLIENT_ID"),
        "client_secret": env("GOOGLE_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=25)
    if not response.ok:
        raise RuntimeError(f"Google token refresh failed ({response.status_code}). Check refresh token and OAuth testing expiry.")
    return response.json()["access_token"]

def drive_request(method, url, access_token, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer " + access_token
    response = requests.request(method, url, headers=headers, timeout=40, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Drive {method} failed ({response.status_code}): {response.text[:300]}")
    return response

def get_memory(access_token):
    result = drive_request("GET", DRIVE_API + "/files", access_token, params={
        "spaces": "appDataFolder", "q": f"name = '{DRIVE_NAME}' and trashed = false",
        "fields": "nextPageToken,files(id,name,modifiedTime)", "page_size": 100,
    }).json()
    files = result.get("files", [])
    if result.get("nextPageToken") or len(files) > 1:
        raise RuntimeError("Multiple matching memory files or paginated results; refusing ambiguous write.")
    if not files:
        raise RuntimeError("No existing v0.2 Drive memory. Sync from the browser first; refusing to create a competing file.")
    file_id = files[0]["id"]
    data = drive_request("GET", DRIVE_API + "/files/" + file_id, access_token, params={"alt": "media"}).json()
    if data.get("format") not in ("shion-core-v0.1", "shion-core-v0.2") or not isinstance(data.get("memories"), list):
        raise RuntimeError("Unexpected memory file format. Refusing overwrite.")
    return file_id, data

def recent_context(memories):
    active = [m for m in memories if isinstance(m, dict) and m.get("status") == "active"]
    active.sort(key=lambda m: (bool(m.get("pinned")), int(m.get("importance", 1)), m.get("created", "")), reverse=True)
    # Do not send private chat memories to external web search. API model sees these excerpts.
    return [{"title": str(m.get("title", ""))[:100], "body": str(m.get("body", ""))[:350],
             "kind": m.get("kind", ""), "importance": m.get("importance", 1)} for m in active[:12]]

def research(memories):
    topic = os.getenv("SHION_TOPIC", "AIã®é·æè¨æ¶ã¨ç¶ç¶çãªå­¦ç¿ã®ç ç©¶").strip()[:180]
    client = OpenAI(api_key=env("OPENAI_API_KEY"), timeout=120)
    prompt = (
        "ããªãã¯SHION COREã®èª¿æ»ã»èå¯ã¨ã¼ã¸ã§ã³ããäººéã®ãããªæè­ãå®éã®ã¢ãã«éã¿ã®å­¦ç¿ãä¸»å¼µããªãã"
        "æå®ãã¼ãã®æè¿ã®æå ±ãã¦ã§ãæ¤ç´¢ããæ ¹æ ãç¢ºèªã§ããäºå®ã¨èªåã®ä»®èª¬ãåºå¥ããã"
        "éå»ã®è¨æ¶ãè¸ã¾ãã¦æ°ããçåã1ã¤èãããåäººæå ±ãã¦ã§ãæ¤ç´¢ã«å¥åããªãã"
        "JSONãªãã¸ã§ã¯ãã®ã¿è¿ããã­ã¼: title (80å­ä»¥å), finding (500å­ä»¥å), "
        "reflection (400å­ä»¥å), next_question (160å­ä»¥å), sources (å®éã«æ¤ç´¢ã§ç¢ºèªããURLã®éåãæå¤§3ä»¶)ã"
        "æ ¹æ ãè¦ã¤ãããªããã°sourcesã¯ç©ºéåãfindingã«æªæ¤è¨¼ã¨æè¨ã"
        f"\nèª¿æ»ãã¼ã: {topic}\néå»ã®è¨æ¶ï¼å¤é¨æ¤ç´¢ã®ã¯ã¨ãªã«å«ããªããã¨ï¼: "
        + json.dumps(recent_context(memories), ensure_ascii=False)
    )
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        tools=[{"type": "web_search"}],
        input=prompt,
        max_output_tokens=1500,
    )
    raw = response.output_text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    result = json.loads(raw)
    for key in ("title", "finding", "reflection", "next_question"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise RuntimeError("Model returned invalid field: " + key)
    urls = result.get("sources", [])
    if not isinstance(urls, list):
        urls = []
    urls = [u for u in urls[:3] if isinstance(u, str) and re.fullmatch(r"https?://[^\s]+", u)]
    # URLs are model-reported, not independently verified by this script.
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": str(uuid.uuid4()),
        "title": "ð " + result["title"][:80],
        "body": "ãèª¿æ»çµæã\n" + result["finding"][:500]
                + "\n\nãèå¯ã»ä»®èª¬ã\n" + result["reflection"][:400]
                + "\n\nãæ¬¡ã®çåã\n" + result["next_question"][:160]
                + "\n\nâ»AIã«ããèªåçæãéè¦ãªäºå®ã¨åºå¸ã¯äººéãç¢ºèªãããã¨ã",
        "kind": "èª¿æ»", "importance": 2, "source": "\n".join(urls),
        "pinned": False, "status": "active", "created": now, "updatedAt": now,
    }

def main():
    access_token = token()
    file_id, data = get_memory(access_token)
    print("Drive memory loaded; existing entries:", len(data["memories"]))
    new_memory = research(data["memories"])
    if os.getenv("DRY_RUN", "false").lower() == "true":
        print("DRY RUN: generated memory (not saved):", new_memory["title"])
        return
    # Re-read immediately before writing, so browser changes during research are retained.
    latest_id, latest = get_memory(access_token)
    if latest_id != file_id:
        raise RuntimeError("Drive file changed during research; refusing write.")
    if any(m.get("id") == new_memory["id"] for m in latest["memories"]):
        raise RuntimeError("Duplicate UUID; refusing write.")
    latest["memories"].append(new_memory)
    latest["format"] = "shion-core-v0.2"  # v0.2 browser supports this format.
    latest["exported"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Back up the original before changing the Drive file, as a GitHub Actions artifact.
    with open("shion-before-write.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    drive_request("PATCH", DRIVE_UPLOAD + "/files/" + file_id, access_token,
                  params={"uploadType": "media"}, headers={"Content-Type": "application/json"},
                  data=json.dumps(latest, ensure_ascii=False).encode("utf-8"))
    print("New research memory saved:", new_memory["title"])

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SHION CORE error:", exc, file=sys.stderr)
        sys.exit(1)
