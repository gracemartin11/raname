"""
mega_rename_datetime.py
Uses a normal rclone remote named "mega" (configured via RCLONE_CONFIG secret).
- Renames videos with date + current time
- If target folder is empty → copy or move videos from source folder, then rename
"""

import subprocess
import json
import os
import sys
from datetime import datetime, timezone

# ============ CONFIG ============
MEGA_FOLDER   = os.environ.get("MEGA_FOLDER")          # required
SOURCE_FOLDER = os.environ.get("SOURCE_FOLDER")        # optional
ACTION        = os.environ.get("ACTION", "copy").lower()  # copy | move
FILE_EXTENSIONS = [
    ext.strip().lower()
    for ext in os.environ.get("FILE_EXTENSIONS", ".mp4").split(",")
    if ext.strip()
]
DRY_RUN  = os.environ.get("DRY_RUN", "true").lower() == "true"
LOG_FILE = os.environ.get("LOG_FILE", "rename_log.txt")

if not MEGA_FOLDER:
    print("ERROR: MEGA_FOLDER must be set")
    sys.exit(1)

if ACTION not in ("copy", "move"):
    print("ERROR: ACTION must be 'copy' or 'move'")
    sys.exit(1)

# Remote paths (remote name is "mega")
TARGET_REMOTE = f"mega:{MEGA_FOLDER}"
SOURCE_REMOTE = f"mega:{SOURCE_FOLDER}" if SOURCE_FOLDER else None

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
    if not SOURCE_REMOTE:
        print("Target is empty and no SOURCE_FOLDER provided. Nothing to do.")
        return []

    print(f"Target empty → {ACTION}ing from '{SOURCE_FOLDER}' ...")

    try:
        source_files = list_remote_files(SOURCE_REMOTE)
    except subprocess.CalledProcessError as e:
        print(f"Failed to list source: {e.stderr}")
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
        print("rclone not found")
        sys.exit(1)

    target_videos = get_video_files(files)
    existing_names = {f["Name"] for f in files}
    log_lines = []
    success_count = 0

    if target_videos:
        print(f"Found {len(target_videos)} video(s). Renaming with date+time...\n")
        for i, old_name in enumerate(target_videos, 1):
            ext = "." + old_name.rsplit(".", 1)[-1].lower()
            new_name = generate_datetime_name(existing_names, i, ext)
            if rename_file(old_name, new_name):
                log_lines.append(f"{old_name} → {new_name}")
                success_count += 1
    else:
        print(f"No videos in '{MEGA_FOLDER}'.")
        transferred = transfer_from_source()
        if not transferred:
            return

        print("\nRenaming transferred files...")
        if not DRY_RUN:
            files = list_remote_files(TARGET_REMOTE)
            existing_names = {f["Name"] for f in files}
            target_videos = get_video_files(files)
        else:
            target_videos = transferred

        for i, old_name in enumerate(target_videos, 1):
            ext = "." + old_name.rsplit(".", 1)[-1].lower()
            new_name = generate_datetime_name(existing_names, i, ext)
            if rename_file(old_name, new_name):
                log_lines.append(f"{old_name} → {new_name}")
                success_count += 1

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nDone. {success_count} file(s) processed.")
    print(f"Log saved to {LOG_FILE}")
    if DRY_RUN:
        print("\n*** DRY RUN — nothing changed. Set dry_run=false to execute. ***")

if __name__ == "__main__":
    main()
