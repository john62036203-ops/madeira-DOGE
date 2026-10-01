#!/usr/bin/env python3
"""madeira-bcd update packs: publish them on the rolling "packs" release.

An update pack is a zip of PE DLLs plus madeira-pack.json (see
.github/workflows/build-pack.yml and docs/madeira-bcd.md, "Update packs").
The app installs one over its own DLLs without a new IPA, provided the pack's
native_abi equals the app's MadeiraNativeABI (tools/native-abi.sh).

Everything lives on ONE prerelease, tag "packs":
  madeira-pack-<run>.zip   the packs (the newest KEEP_PACKS are kept)
  index.json               what the app reads: every pack (newest first) with
                           its native ABI, and the recent IPA builds, so the
                           app can say "this pack needs app build N"
The assets hold only DLLs built from this repository's sources -- never an
IPA, Apple's converter or Microsoft's runtime.

  pack-index.py add-pack <pack.zip> <madeira-pack.json>
  pack-index.py add-app <build> <native_abi> <commit> <run_url>

Needs GH_TOKEN (contents: write) and GITHUB_REPOSITORY.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GH_TOKEN"]
TAG = os.environ.get("PACK_TAG", "packs")
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
KEEP_PACKS = 25
KEEP_APPS = 12

BODY = ("Update packs for Madeira (madeira-bcd): PE DLLs built from this repository "
        "(the D3D12 runtime), installed from the app's Settings > Updates without "
        "reinstalling the IPA. index.json lists them with the app build they fit. "
        "No IPA and no third-party binary is published here.")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def call(method, url, data=None, ctype="application/json"):
    headers = {"Authorization": "Bearer " + TOKEN,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    body = None
    if data is not None:
        body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode()
        headers["Content-Type"] = ctype
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def release():
    st, rel = call("GET", "%s/repos/%s/releases/tags/%s" % (API, REPO, TAG))
    if st == 200:
        return rel
    st, rel = call("POST", "%s/repos/%s/releases" % (API, REPO), {
        "tag_name": TAG, "target_commitish": os.environ.get("GITHUB_SHA", "main"),
        "name": "Madeira update packs", "body": BODY,
        "prerelease": True, "make_latest": "false"})
    if st not in (200, 201):
        sys.exit("cannot create the %s release: %s %s" % (TAG, st, rel))
    print("created release %s" % TAG)
    return rel


def delete_asset(rel, name):
    for a in rel.get("assets", []):
        if a["name"] == name:
            call("DELETE", "%s/repos/%s/releases/assets/%d" % (API, REPO, a["id"]))


def upload(rel, name, data, ctype):
    delete_asset(rel, name)
    url = "%s/repos/%s/releases/%d/assets?name=%s" % (UPLOADS, REPO, rel["id"], urllib.parse.quote(name))
    st, res = call("POST", url, data, ctype)
    if st not in (200, 201):
        sys.exit("upload of %s failed: %s %s" % (name, st, res))
    return res["browser_download_url"]


def read_index(rel):
    for a in rel.get("assets", []):
        if a["name"] == "index.json":
            try:
                with urllib.request.urlopen(a["browser_download_url"], timeout=60) as resp:
                    return json.loads(resp.read())
            except Exception as e:  # a broken index is rebuilt, not fatal
                print("::warning::index.json unreadable (%s) -- starting a new one" % e)
    return {"format": 1, "packs": [], "apps": []}


def write_index(rel, index):
    index["format"] = 1
    index["repo"] = REPO
    index["updated"] = now()
    upload(rel, "index.json", json.dumps(index, indent=1).encode(), "application/json")


def add_pack(zip_path, manifest_path):
    rel = release()
    man = json.load(open(manifest_path))
    name = "madeira-pack-%d.zip" % int(man["build"])
    url = upload(rel, name, open(zip_path, "rb").read(), "application/zip")
    entry = dict(man)
    entry["asset"] = name
    entry["url"] = url
    entry["size"] = os.path.getsize(zip_path)
    index = read_index(rel)
    packs = [p for p in index.get("packs", []) if p.get("build") != man["build"]]
    packs.insert(0, entry)
    rel = release()   # fresh asset list for the deletes below
    for old in packs[KEEP_PACKS:]:
        delete_asset(rel, old.get("asset", ""))
    index["packs"] = packs[:KEEP_PACKS]
    write_index(release(), index)
    print("published %s (native ABI %s) -> %s" % (name, man["native_abi"], url))


def add_app(build, abi, commit, run_url):
    rel = release()
    index = read_index(rel)
    apps = [a for a in index.get("apps", []) if a.get("build") != int(build)]
    apps.insert(0, {"build": int(build), "native_abi": abi, "commit": commit,
                    "run_url": run_url, "created": now()})
    index["apps"] = apps[:KEEP_APPS]
    write_index(rel, index)
    print("recorded app build %s (native ABI %s)" % (build, abi))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "add-pack":
        add_pack(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 6 and sys.argv[1] == "add-app":
        add_app(*sys.argv[2:])
    else:
        sys.exit(__doc__)
