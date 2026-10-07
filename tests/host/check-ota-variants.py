#!/usr/bin/env python3
"""Exercise actual app staging, manifests, email links and paired retention.

No Apple signing material, network requests or outgoing mail are used here.
Real codesign and IPA packaging run in the macOS IPA workflow.
"""
import hashlib
import html
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import zipfile
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ota_variants", ROOT / "tools/ota-variants.py")
ota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota)


def plist(path, value=None):
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            plistlib.dump(value, f, fmt=plistlib.FMT_BINARY)
    with path.open("rb") as f:
        return plistlib.load(f)


def snapshot(root):
    return {str(p.relative_to(root)): ("link", p.readlink().as_posix()) if p.is_symlink()
            else ("file", hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob("*") if p.is_file() or p.is_symlink()}


class Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.urls = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.append(dict(attrs)["href"])


with tempfile.TemporaryDirectory(prefix="madeira-ota-contracts-") as directory:
    tmp = Path(directory)
    source = tmp / "archive" / "Madeira.app"
    app_info = dict(CFBundleIdentifier="com.willfaust.mythicemu", CFBundleDisplayName="Madeira",
                    CFBundleName="Madeira", CFBundleExecutable="Madeira", CFBundleVersion="413",
                    CFBundleShortVersionString="0.1.413", MadeiraNativeABI="unchanged-abi",
                    BGTaskSchedulerPermittedIdentifiers=["com.willfaust.mythicemu.download.*"],
                    CFBundleURLTypes=[dict(CFBundleURLSchemes=["madeira"])])
    plist(source / "Info.plist", app_info)
    (source / "Madeira").write_bytes(b"unchanged native executable\x00")
    extension = source / "Extensions" / "MadeiraMemoryHost.appex"
    plist(extension / "Info.plist", dict(CFBundleIdentifier="com.willfaust.mythicemu.MemoryHost",
                                        CFBundleExecutable="MadeiraMemoryHost"))
    (extension / "MadeiraMemoryHost").write_bytes(b"unchanged extension executable\x00")
    framework = source / "Frameworks" / "Renderer.framework"
    (framework / "Versions" / "A").mkdir(parents=True)
    (framework / "Versions" / "A" / "Renderer").write_bytes(b"same renderer\x00")
    (framework / "Renderer").symlink_to("Versions/A/Renderer")
    before = snapshot(source)
    staged = ota.stage_variants(source, tmp / "out")
    assert [name for name, _ in staged] == ["Madeira", "Madeira2"]
    primary = staged[0][1] / "Payload" / "Madeira.app"
    secondary = staged[1][1] / "Payload" / "Madeira2.app"
    assert snapshot(primary) == before == snapshot(source)
    changed = {name for name, value in snapshot(secondary).items() if value != before[name]}
    assert changed == {"Info.plist", "Extensions/MadeiraMemoryHost.appex/Info.plist"}
    expected = dict(app_info, CFBundleIdentifier="com.willfaust.mythicemu2",
                    CFBundleDisplayName="Madeira2", CFBundleName="Madeira2",
                    BGTaskSchedulerPermittedIdentifiers=["com.willfaust.mythicemu2.download.*"])
    assert plist(secondary / "Info.plist") == expected
    assert plist(secondary / "Extensions/MadeiraMemoryHost.appex/Info.plist")["CFBundleIdentifier"] == \
        "com.willfaust.mythicemu2.MemoryHost"
    print("PASS: primary app bytes remain intact; secondary changes identity metadata only, including MemoryHost; binaries and framework symlinks match")

    data = ota.publication("0.1.413", 413, True)
    for row in data["variants"]:
        for field in ("ipa_url", "manifest_url", "page_url"):
            row[field] = f'https://private.example.test/{row["name"]}/{field}?token=a&quoted="b"'
    pages = tmp / "pages"
    ota.render(data, pages)
    assert len(list(pages.iterdir())) == 5  # two manifests, two per-app pages, one combined page
    for row in data["variants"]:
        manifest = plist(pages / ota.manifest_key(row["name"], data["version"]))["items"][0]
        assert manifest["metadata"]["bundle-identifier"] == row["bundle_id"]
        assert manifest["metadata"]["bundle-version"] == "0.1.413"
        assert manifest["assets"][0]["url"] == row["ipa_url"]
        links = Links((pages / ota.page_key(row["name"], data["version"])).read_text()).urls
        assert len(links) == 1 and urlparse(links[0]).scheme == "itms-services"
        assert parse_qs(urlparse(links[0]).query)["url"] == [row["manifest_url"]]
    combined = Links((pages / "kurulum-0.1.413.html").read_text()).urls
    assert len(combined) == 2
    message = ota.email_message(data, "sender@example.test", "owner@example.test")
    mail_html = message.get_body(preferencelist=("html",)).get_content()
    assert Links(mail_html).urls == [row["page_url"] for row in data["variants"]]
    assert "Madeira Kurulum" in mail_html and "Madeira2 Kurulum" in mail_html
    assert "Madeira ve Madeira2" in message["Subject"]
    assert all(row["page_url"] in message.get_body(preferencelist=("plain",)).get_content()
               for row in data["variants"])
    assert 'quoted="b"' not in mail_html and html.escape('quoted="b"') in mail_html
    single = ota.publication("0.1.413", 413, False)
    single["variants"][0].update(data["variants"][0])
    assert len(Links(ota.email_message(single, "a@example.test", "b@example.test")
                     .get_body(preferencelist=("html",)).get_content()).urls) == 1
    print("PASS: two separate manifests and installation buttons point to the matching IPA; one multipart email contains both links and escapes signed URLs")

    objects = {"Development.p12": 25, "unrelated/keep.bin": 17,
               "ota/Madeira-0.1.410.ipa": 100, "ota/manifest-0.1.410.plist": 6,
               "kurulum-0.1.410.html": 4,
               "ota/Madeira-0.1.411.ipa": 100, "ota/Madeira2-0.1.411.ipa": 200,
               "ota/manifest-0.1.411.plist": 6, "ota/manifest-Madeira2-0.1.411.plist": 6,
               "kurulum-0.1.411.html": 4, "kurulum-Madeira-0.1.411.html": 4,
               "kurulum-Madeira2-0.1.411.html": 4}
    listing = lambda rows: '\n'.join(f"2026-10-06 00:00:00 {size} {key}" for key, size in rows.items())
    plan = ota.prune_plan(listing(objects), 306, 1000, 2, "0.1.412")
    assert plan["used"] == 672 and plan["builds"] == 2
    assert set(plan["delete"]) == {"ota/Madeira-0.1.410.ipa", "ota/manifest-0.1.410.plist", "kurulum-0.1.410.html"}
    full = ota.prune_plan(listing(objects), 306, 400, 10, "0.1.412")
    assert full["used"] == 348 and full["builds"] == 1
    assert set(full["delete"]) == set(objects) - {"Development.p12", "unrelated/keep.bin"}
    current = {"Development.p12": 25, "unrelated/keep.bin": 17,
               "ota/Madeira-0.1.412.ipa": 100, "ota/Madeira2-0.1.412.ipa": 200,
               "kurulum-0.1.412.html": 6}
    replace = ota.prune_plan(listing(current), 306, 1000, 10, "0.1.412")
    assert replace == dict(delete=[], used=354, limit=1000, builds=1)
    too_big = ota.prune_plan(listing(current), 1000, 500, 10, "0.1.412")
    assert too_big["used"] > too_big["limit"] and not too_big["delete"]
    current.pop("ota/Madeira-0.1.412.ipa")
    assert ota.prune_plan(listing(current), 0, 1000, 10, "0.1.413")["builds"] == 1
    print("PASS: pairs count as one build; retention deletes both identities together, protects current and signing objects, and budgets both new IPAs before upload")

subprocess.run(["bash", "-n", str(ROOT / "tools/sign-and-publish-ota.sh")], check=True)
workflow = (ROOT / ".github/workflows/build-ipa.yml").read_text()
assert workflow.count("xcodebuild -project app/Madeira.xcodeproj") == 1
assert workflow.count("run: bash tools/sign-and-publish-ota.sh") == 1
assert "build-out/Madeira2-0.1.${{ github.run_number }}-unsigned.ipa" in workflow
assert "python3 tests/host/check-ota-variants.py" in workflow
signer = (ROOT / "tools/sign-and-publish-ota.sh").read_text()
assert signer.count('python3 "$OTA_HELPER" mail') == 1
assert signer.index('for name in "${NAMES[@]}"; do\n  s3 cp') < signer.index('python3 "$OTA_HELPER" mail')
print("PASS: one archive, one paired signing invocation and one email invocation; shell syntax valid")

# Run the actual shell orchestration with local tool doubles. The macOS-only
# signing commands are substituted; storage, links and SMTP never use a network.
tool_double = r'''#!/usr/bin/env python3
from pathlib import Path
import datetime, json, os, plistlib, shutil, sys, zipfile
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
bucket = Path(os.environ['FIXTURE_BUCKET'])
log = Path(os.environ['FIXTURE_CALLS'])
def record(value):
    with log.open('a') as f: f.write(json.dumps(value)+'\n')
def stored(url): return bucket / url.split('/', 3)[3]
if tool == 'aws':
    _, action, *rest = args
    if action == 'cp':
        src, dst = rest[:2]
        if dst.startswith('s3://') and 'Madeira2-' in dst and dst.endswith('.ipa') and os.environ.get('FAIL_UPLOAD'):
            sys.exit(8)
        target = stored(dst) if dst.startswith('s3://') else Path(dst)
        source = stored(src) if src.startswith('s3://') else Path(src)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        record(['cp', src.split('/')[-1], dst.split('/')[-1]])
    elif action == 'presign': print('https://fixture.invalid/' + rest[0].split('/', 3)[3] + '?token=x&signature=y')
    elif action == 'ls':
        for p in bucket.rglob('*'):
            if p.is_file(): print('2026-10-06 00:00:00', p.stat().st_size, p.relative_to(bucket))
    elif action == 'rm': stored(rest[0]).unlink()
elif tool == 'uuidgen': print('00000000-0000-0000-0000-000000000001')
elif tool == 'security':
    if args[0] == 'find-identity': print('1) FIXTURE_ID')
    elif args[0] == 'cms':
        sys.stdout.buffer.write(plistlib.dumps(dict(Entitlements={'application-identifier':'FIXTURE.test'},
            TeamIdentifier=['FIXTURE'], ExpirationDate=datetime.datetime(2099,1,1))))
    elif args[0] == 'import': record(['certificate-import'])
elif tool == 'plistbuddy':
    path = Path(args[-1]); value = plistlib.loads(path.read_bytes()); command = args[args.index('-c')+1]
    for part in command.removeprefix('Print :').split(':'):
        value = value[int(part)] if isinstance(value,list) else value[part]
    if '-x' in args: sys.stdout.buffer.write(plistlib.dumps(value))
    else: print(value)
elif tool == 'codesign':
    target = Path(args[-1]); identifier = None
    if target.is_dir() and (target/'Info.plist').exists(): identifier = plistlib.loads((target/'Info.plist').read_bytes())['CFBundleIdentifier']
    if '--verify' not in args and identifier == 'com.willfaust.mythicemu2' and os.environ.get('FAIL_SIGN'): sys.exit(7)
    record(['verify' if '--verify' in args else 'sign', identifier])
elif tool == 'ditto':
    if '-x' in args:
        with zipfile.ZipFile(args[-2]) as z: z.extractall(args[-1])
    else:
        source, target = Path(args[-2]), Path(args[-1])
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for p in source.rglob('*'):
                if p.is_file(): z.write(p, p.relative_to(source.parent))
'''

with tempfile.TemporaryDirectory(prefix='madeira-ota-flow-') as directory:
    tmp = Path(directory)
    commands = tmp / 'bin'; commands.mkdir()
    driver = commands / 'driver'; driver.write_text(tool_double); driver.chmod(0o755)
    for name in ('aws', 'security', 'plistbuddy', 'codesign', 'ditto', 'uuidgen'):
        (commands / name).symlink_to(driver)
    script = tmp / 'sign-and-publish-ota.sh'
    script.write_text(signer.replace('/usr/libexec/PlistBuddy', str(commands / 'plistbuddy')))
    proxy = tmp / 'ota-variants.py'
    proxy.write_text('import json,os,subprocess,sys\n'
                     'from pathlib import Path\n'
                     'if sys.argv[1] == "mail":\n'
                     '    data=json.loads(Path(sys.argv[2]).read_text())\n'
                     '    with Path(os.environ["FIXTURE_CALLS"]).open("a") as f:\n'
                     '        f.write(json.dumps(["mail",[r["name"] for r in data["variants"]]])+"\\n")\n'
                     'else:\n'
                     f'    sys.exit(subprocess.call([sys.executable,{str(ROOT / "tools/ota-variants.py")!r}]+sys.argv[1:]))\n')
    inputs = []
    for name, identifier in ota.VARIANTS:
        ipa = tmp / f'{name}-input.ipa'
        with zipfile.ZipFile(ipa,'w') as z:
            info = dict(CFBundleIdentifier=identifier, CFBundleDisplayName=name, CFBundleExecutable='Madeira',
                        CFBundleShortVersionString='0.1.413', CFBundleVersion='413')
            z.writestr(f'Payload/{name}.app/Info.plist', plistlib.dumps(info))
            z.writestr(f'Payload/{name}.app/Madeira', b'unchanged executable')
            z.writestr(f'Payload/{name}.app/Extensions/MemoryHost.appex/Info.plist',
                       plistlib.dumps(dict(CFBundleIdentifier=identifier+'.MemoryHost')))
        inputs.append(ipa)
    for mode in ('success', 'second-sign-fails', 'second-upload-fails'):
        case = tmp / mode; case.mkdir()
        bucket = case / 'bucket'; bucket.mkdir()
        (bucket / 'Development.p12').write_bytes(b'fixture, not signing material')
        (bucket / 'Development.mobileprovision').write_bytes(b'fixture, not a provisioning profile')
        env = dict(os.environ, PATH=str(commands)+os.pathsep+os.environ['PATH'], RUNNER_TEMP=str(case),
                   FIXTURE_BUCKET=str(bucket), FIXTURE_CALLS=str(case / 'calls.jsonl'),
                   R2_ACCOUNT_ID='fixture', R2_ACCESS_KEY_ID='fixture', R2_SECRET_ACCESS_KEY='fixture',
                   R2_BUCKET='bucket', SIGN_P12_PASSWORD='fixture', OTA_MAIL_USER='fixture@example.test',
                   OTA_MAIL_APP_PASSWORD='fixture', OTA_MAIL_TO='fixture@example.test',
                   FAIL_SIGN='1' if mode=='second-sign-fails' else '',
                   FAIL_UPLOAD='1' if mode=='second-upload-fails' else '')
        result = subprocess.run(['bash',str(script),str(inputs[0]),'413',str(inputs[1])],
                                env=env, capture_output=True, text=True)
        assert 'https://fixture.invalid/' not in result.stdout + result.stderr
        calls = [json.loads(line) for line in (case / 'calls.jsonl').read_text().splitlines()]
        assert calls.count(['certificate-import']) == 1, result.stderr
        mailed = [call for call in calls if call[0]=='mail']
        if mode == 'success':
            if result.returncode: raise AssertionError(result.stderr)
            assert mailed == [['mail',['Madeira','Madeira2']]]
            for name, identifier in ota.VARIANTS:
                with zipfile.ZipFile(bucket / 'ota' / f'{name}-0.1.413.ipa') as z:
                    assert plistlib.loads(z.read(f'Payload/{name}.app/Info.plist'))['CFBundleIdentifier'] == identifier
                    assert z.read(f'Payload/{name}.app/Madeira') == b'unchanged executable'
                    assert z.read(f'Payload/{name}.app/embedded.mobileprovision') == b'fixture, not a provisioning profile'
                assert ['verify',identifier] in calls
            assert len(list(bucket.glob('*.html'))) == 3
        else:
            assert result.returncode and not mailed
            assert not list(bucket.glob('*.html'))
            if mode == 'second-sign-fails': assert not (bucket/'ota').exists()
    print('PASS: actual shell flow imports one certificate, signs both identities and sends one mail; a second signing/upload failure sends none; private URLs stay out of output (local tool doubles)')
