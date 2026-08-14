import os
import csv
import subprocess
from tqdm import tqdm
from collections import defaultdict

# Adjust depending where trendconvert.py is
TRENDCONVERT = r"C:\Users\Administrator\Desktop\HST Translator\HST\trendconvert\trendconvert.py"


def run_info(hst):
    """
    Runs: python trendconvert.py <hst> -info
    Returns a dict with parsed information or {"Error": "..."} on failure.
    """
    try:
        cmd = ["python", TRENDCONVERT, hst, "-info"]
        r = subprocess.run(cmd, text=True, capture_output=True, timeout=20)

        if r.returncode != 0:
            return {"Error": "trendconvert failed"}

        output = r.stdout.strip()
        if not output:
            return {"Error": "empty output"}

        info = {}

        for line in output.splitlines():
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            key, val = parts[0].strip(), parts[1].strip()

            info[key] = val

        return info

    except Exception as e:
        return {"Error": str(e)}


def find_hst_files():
    drives = [f"{chr(c)}:\\" for c in range(ord("C"), ord("Z") + 1)]
    all_files = []

    for d in drives:
        if not os.path.exists(d):
            continue

        for root, dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".hst"):
                    all_files.append(os.path.join(root, f))

    return all_files


def folder_signature(path):
    parts = os.path.dirname(path).replace(":", "").replace("\\", "/").split("/")
    parts = [p.replace(" ", "_") for p in parts if p]
    return "__".join(parts[-3:])


if __name__ == "__main__":
    print("Scanning HST files...")

    hsts = find_hst_files()
    print(f"Found {len(hsts)} HST files.")

    rows = []
    dupe_map = defaultdict(list)

    for hst in tqdm(hsts, desc="Processing HST files", ncols=100):
        info = run_info(hst)

        base = os.path.splitext(os.path.basename(hst))[0]
        sig = folder_signature(hst)

        if "Error" in info:
            rows.append([hst, base, sig, "READ ERROR", "", "", "", "", "", "", ""])
            continue

        version = info.get("Version", "")
        start = info.get("Start", "")
        end = info.get("End", "")
        period = info.get("Period", "")
        samples = info.get("Samples", "")
        numfiles = info.get("Files", "")

        # duplicate grouping
        dupe_key = (base, version, start, end)
        dupe_map[dupe_key].append(hst)

        rows.append([
            hst, base, sig, version, start, end, "", numfiles, period, samples
        ])

    # assign duplicate group numbers
    dupe_id = {}
    gid = 1
    for key, paths in dupe_map.items():
        if len(paths) > 1:
            for p in paths:
                dupe_id[p] = gid
            gid += 1

    out = "all_hsts_report.csv"

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "FullPath", "BaseName", "FolderSignature",
            "Version", "StartTime", "EndTime",
            "DurationHours", "NumDataFiles", "SamplePeriodMs",
            "TotalSamples", "DuplicateGroup"
        ])

        for r in rows:
            path = r[0]
            w.writerow(r + [dupe_id.get(path, "")])

    print(f"✔ Report written to: {out}")
