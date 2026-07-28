"""
mega_rename_datetime.py
- Renames video files in a Mega.nz folder using date + current time + sequential number
- If the target folder has NO videos → copies (or moves) all videos from a source folder into the target
- Then renames them with date/time format

Environment variables (required):
    MEGA_USER          Mega.nz email
    MEGA_PASS          rclone-obscured password
    MEGA_FOLDER        Target folder inside Mega (e.g. fbreels)

Optional:
    SOURCE_FOLDER      Folder to copy/move FROM when target is empty
    ACTION             "copy" or "move" (default: copy)
    FILE_EXTENSIONS    comma-separated, default ".mp4"
    DRY_RUN            "true" / "false" (default: true)
    LOG_FILE           default: rename_log.txt
"""

import subprocess
import json
import os
import sys
from datetime import datetime, timezone

# ============ CONFIG ============
MEGA_USER = os.environ.get("MEGA_USER")
MEGA_PASS = os.environ.get("MEGA_PASS")
MEGA_FOLDER = os.environ.get("MEGA_FOLDER")
SOURCE_FOLDER = os.environ.get("SOURCE_FOLDER")          # only used when target is empty
ACTION = os.environ.get("ACTION", "copy").lower()        # "copy" or "move"
FILE_EXTENSIONS = [
    ext.strip().lower()
    for ext in os.environ.get("FILE_EXTENSIONS", ".mp4").split(",")
    if ext.strip()
]
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
LOG_FILE = os.environ.get("LOG_FILE", "rename_log.txt")

if not MEGA_USER or not MEGA_PASS or not MEGA_FOLDER:
    print("ERROR: MEGA_USER, MEGA_PASS and MEGA_FOLDER must be set.")
    sys.exit(1)

if ACTION not in ("copy", "move"):
    print("ERROR: ACTION must be 'copy' or 'move'")
    sys.exit(1)

RCLONE_REMOTE = f":mega,user={MEGA_USER},pass={MEGA_PASS}"
TARGET_REMOTE = f"{RCLONE_REMOTE}:{MEGA_FOLDER}"
SOURCE_REMOTE = f"{RCLONE_REMOTE}:{SOURCE_FOLDER}" if SOURCE_FOLDER else None

# =================================

def list_remote_files(remote_path: str):
    print(f"Listing → {remote_path}")
    result = subprocess.run(
        ["rclone", "lsjson", remote_path],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)

def get_video_files(files):
    return [
        f["Name"] for f in files
        if not f.get("IsDir", False)
        and any(f["Name"].lower().endswith(ext) for ext in FILE_EXTENSIONS)
    ]

def generate_datetime_name(existing_names: set, index: int, ext: str) -> str:
    """Create unique name: 20260728_051932_001.mp4"""
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    while True:
        candidate = f"{now}_{index:03d}{ext}"
        if candidate not in existing_names:
            existing_names.add(candidate)
            return candidate
        index += 1

def rclone_cmd(cmd: list, dry_run: bool = True) -> bool:
    if dry_run:
        print(f"[DRY RUN] Would run: rclone {' '.join(cmd)}")
        return True
    try:
        subprocess.run(["rclone"] + cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {e.stderr.strip()}")
        return False

def rename_file(old_name: str, new_name: str) -> bool:
    old_path = f"{TARGET_REMOTE}/{old_name}"
    new_path = f"{TARGET_REMOTE}/{new_name}"
    success = rclone_cmd(["moveto", old_path, new_path], dry_run=DRY_RUN)
    if success:
        print(f"{'Would rename' if DRY_RUN else 'Renamed'}: {old_name} → {new_name}")
    return success

def transfer_from_source():
    """Copy or move all videos from SOURCE_FOLDER into MEGA_FOLDER"""
    if not SOURCE_REMOTE:
        print("Target folder is empty and no SOURCE_FOLDER was provided. Nothing to do.")
        return []

    print(f"Target folder empty → {ACTION}ing videos from '{SOURCE_FOLDER}' ...")

    try:
        source_files = list_remote_files(SOURCE_REMOTE)
    except subprocess.CalledProcessError as e:
        print(f"Failed to list source folder: {e.stderr}")
        sys.exit(1)

    videos = get_video_files(source_files)
    if not videos:
        print(f"No videos found in source folder '{SOURCE_FOLDER}'")
        return []

    transferred = []
    for name in videos:
        src = f"{SOURCE_REMOTE}/{name}"
        dst = f"{TARGET_REMOTE}/{name}"
        cmd = ["copyto" if ACTION == "copy" else "moveto", src, dst]
        if rclone_cmd(cmd, dry_run=DRY_RUN):
            print(f"{'Would ' + ACTION if DRY_RUN else ACTION.capitalize() + 'd'}: {name}")
            transferred.append(name)
    return transferred

def main():
    try:
        files = list_remote_files(TARGET_REMOTE)
    except subprocess.CalledProcessError as e:
        print(f"Failed to list target folder: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("rclone not found. Install it first.")
        sys.exit(1)

    target_videos = get_video_files(files)
    existing_names = {f["Name"] for f in files}
    log_lines = []
    success_count = 0

    # ---------- CASE 1: Target has videos → just rename ----------
    if target_videos:
        print(f"Found {len(target_videos)} video(s) in target. Renaming with date+time...\n")
        for i, old_name in enumerate(target_videos, 1):
            ext = "." + old_name.rsplit(".", 1)[-1].lower()
            new_name = generate_datetime_name(existing_names, i, ext)
            if rename_file(old_name, new_name):
                log_lines.append(f"{old_name} → {new_name}")
                success_count += 1

    # ---------- CASE 2: Target is empty → copy/move from source, then rename ----------
    else:
        print(f"No videos found in '{MEGA_FOLDER}'.")
        transferred = transfer_from_source()
        if not transferred:
            return

        # After transfer, rename the newly arrived files
        print("\nNow renaming the transferred files with date+time...")
        # Refresh the list (in dry-run we still pretend)
        if not DRY_RUN:
            files = list_remote_files(TARGET_REMOTE)
            existing_names = {f["Name"] for f in files}
            target_videos = get_video_files(files)
        else:
            target_videos = transferred  # pretend

        for i, old_name in enumerate(target_videos, 1):
            ext = "." + old_name.rsplit(".", 1)[-1].lower()
            new_name = generate_datetime_name(existing_names, i, ext)
            if rename_file(old_name, new_name):
                log_lines.append(f"{old_name} → {new_name}")
                success_count += 1

    # Write log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nDone. {success_count} file(s) processed.")
    print(f"Log saved to {LOG_FILE}")
    if DRY_RUN:
        print("\n*** DRY RUN — nothing was changed. Set DRY_RUN=false to execute. ***")

if __name__ == "__main__":
    main()
