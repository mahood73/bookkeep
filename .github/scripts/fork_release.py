"""Reserve a new fork-only tag, then record the successfully published image."""
import json
import os
from pathlib import Path
import re
import urllib.request

REPOSITORY = "mahood73/bookkeep"
IMAGE = "ghcr.io/mahood73/bookkeep"


def next_tag(tags, version):
    pattern = re.compile(r"v" + re.escape(version) + r"-hoodhaus\.(\d+)$")
    numbers = [int(match[1]) for tag in tags if (match := pattern.fullmatch(tag))]
    return f"v{version}-hoodhaus.{max(numbers, default=0) + 1}"


def api(path, data=None):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SystemExit("Release publication is restricted to the HoodHaus fork")
    if os.environ.get("GITHUB_REF") != "refs/heads/develop":
        raise SystemExit("Releases must come from the fork's develop branch")
    if os.environ["RELEASE_ACTION"] == "reserve":
        version = Path(".github/fork-version.txt").read_text().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise SystemExit("Invalid fork base version")
        tags = []
        page = 1
        while True:
            rows = api(f"tags?per_page=100&page={page}")
            tags.extend(row["name"] for row in rows)
            if len(rows) < 100:
                break
            page += 1
        tag = next_tag(tags, version)
        # Reserve before pushing the image. A failed build may leave a tag gap;
        # a retry reserves a fresh tag rather than overwriting an existing image.
        api("git/refs", {"ref": "refs/tags/" + tag, "sha": os.environ["GITHUB_SHA"]})
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"tag={tag}\n")
        print("Reserved " + tag)
    elif os.environ["RELEASE_ACTION"] == "publish":
        tag = os.environ["RELEASE_TAG"]
        digest = os.environ["IMAGE_DIGEST"]
        if not re.fullmatch(r"v\d+\.\d+\.\d+-hoodhaus\.\d+", tag):
            raise SystemExit("Invalid fork release tag")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise SystemExit("Invalid image digest")
        ref = api("git/ref/tags/" + tag)
        if ref["object"]["sha"] != os.environ["GITHUB_SHA"]:
            raise SystemExit("Release tag does not match the built commit")
        image = f"{IMAGE}:{tag}@{digest}"
        api("releases", {"tag_name": tag, "name": tag, "make_latest": "false",
                         "body": f"Image (amd64 and arm64):\n\n`{image}`\n\nSource: {os.environ['GITHUB_SHA']}"})
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(f"Published image: `{image}`\n")
        print("Published " + image)
    else:
        raise SystemExit("Unknown release action")


if __name__ == "__main__":
    main()
