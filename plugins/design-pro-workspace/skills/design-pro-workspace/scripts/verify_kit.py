#!/usr/bin/env python3
"""Checks files fetched from the Design Pro Workspace Kit before the Updater installs them (plugin file; never fetched).

Usage: python3 -I verify_kit.py KIT SKILL_DIR
  KIT        the folder the Kit's channel files landed in (holds version.json and assets/...)
  SKILL_DIR  this plugin's skill folder (holds SKILL.md with its "Skill version:" line)

The Kit's version.json lists the SHA-256 of each released file under "files", keyed by the path inside the channel
folder (for example "assets/prompts.json"). Every file the Updater installs must be there and match, and the plugin
must be at least the Kit's "minSkill". Prints one line and exits:
  0  OK <version>
  3  PLUGIN-OLD <minSkill> <this plugin's version>   (the plugin must be updated first: nothing is installed)
  4  NEEDS-OK <reason>                               (the files can't be checked: only the person may install them)
  2  FAILED <reason>                                 (something is missing or unreadable)
Only the Kit's three page/instruction files are installed unattended; Python code always comes from the plugin.
"""
import hashlib
import json
import os
import re
import sys

INSTALL = ('assets/workspace-template.html', 'assets/capabilities-template.json', 'assets/prompts.json')
VER = re.compile(r'\d{4}-\d{2}-\d{2}[a-z]')


def say(code, line):
    print(line)
    return code


def skill_version(skill_dir):
    try:
        for line in open(os.path.join(skill_dir, 'SKILL.md'), encoding='utf-8'):
            m = re.match(r'Skill version: (\S+)', line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return ''


def main(kit, skill_dir):
    try:
        ver = json.load(open(os.path.join(kit, 'version.json'), encoding='utf-8'))
    except (OSError, ValueError) as e:
        return say(2, 'FAILED the Kit\'s version.json couldn\'t be read (%s)' % str(e)[:80])
    if not isinstance(ver, dict) or not VER.fullmatch(str(ver.get('version') or '')):
        return say(2, 'FAILED the Kit\'s version.json has no version')
    have = skill_version(skill_dir)
    if not VER.fullmatch(have):
        return say(2, 'FAILED the plugin\'s SKILL.md has no Skill version line')
    need = str(ver.get('minSkill') or '')
    if need and (not VER.fullmatch(need) or need > have):
        return say(3, 'PLUGIN-OLD %s %s' % (need[:20], have))
    files = ver.get('files')
    if not isinstance(files, dict) or not files:
        return say(4, 'NEEDS-OK the Kit lists no file checksums')
    for rel in INSTALL:
        want = files.get(rel)
        if not isinstance(want, str) or not re.fullmatch(r'[0-9a-f]{64}', want.lower()):
            return say(4, 'NEEDS-OK the Kit lists no checksum for %s' % rel)
        try:
            got = hashlib.sha256(open(os.path.join(kit, *rel.split('/')), 'rb').read()).hexdigest()
        except OSError:
            return say(2, 'FAILED %s is missing' % rel)
        if got != want.lower():
            return say(4, 'NEEDS-OK %s doesn\'t match its checksum' % rel)
    return say(0, 'OK %s' % ver['version'])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
