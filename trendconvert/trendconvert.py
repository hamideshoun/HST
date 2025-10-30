import sys
import struct
import math
import os
from datetime import datetime, timedelta
import argparse
from openpyxl import Workbook
import csv

class MasterHeader:
    Title = None
    ID = None
    Type = None
    Version = None
    Max_nr_files = None
    Files_created = None
    Next = None
    Addon = None
    Datafile_names = None
    Data_headers = None

class Header:
    ID = None
    Type = None
    Version = None
    StartEvNo = None
    LogName = None
    Mode = None
    Area = None
    Priv = None
    FileType = None
    SamplePediod = None
    EngUnits = None
    Format = None
    StartTime = None
    EndTime = None
    DataLength = None
    FilePointer = None
    EndEvNo = None

class EngScale:
    RawZero = None
    RawFull = None
    EngZero = None
    EngFull = None

def parseArgs():
    parser = argparse.ArgumentParser("trendconvert")
    parser.add_argument("file", type=str, help="Filename (TRENDFILE.HST)")
    parser.add_argument("-s", default=False, action="store_true", help="Strip directories from HST data filenames.")
    parser.add_argument("-o", metavar="TYPE", type=str, choices=["xls", "csv"], default="csv", help="Output file type")
    parser.add_argument("-e", default=False, action="store_true", help="Examine master header for dates in data files.")
    parser.add_argument("-start", type=str, metavar="DATE", help="Start date (YYYY-MM-DD)")
    parser.add_argument("-stop", type=str, metavar="DATE", help="End date (YYYY-MM-DD)")
    parser.add_argument("-f", type=int, metavar="NUM", help="Select file to export.")
    parser.add_argument("-d", default=True, action="store_false", help="Do not discard invalid values from samples.")
    parser.add_argument("-p", type=int, default=1, metavar="NUM", help="Number of decimals shown in values. (Default: 1)")
    parser.add_argument("-outdir", type=str, default=".", help="Output directory for generated files")
    args = parser.parse_args()
    return args

def readMasterHeader(f):
    m = MasterHeader()
    m.Title = f.read(128).decode("cp1252").rstrip("\x00")
    m.ID = f.read(8).decode("cp1252").rstrip("\x00")
    m.Type = int.from_bytes(f.read(2), "little", signed=False)
    m.Version = int.from_bytes(f.read(2), "little")
    tAlign = f.read(4)
    tMode = f.read(4)
    m.Max_nr_files = int.from_bytes(f.read(2), "little")
    m.Files_created = int.from_bytes(f.read(2), "little")
    m.Next = f.read(2)
    m.Addon = f.read(2)
    tAlign = f.read(20)
    m.Datafile_names = []
    m.Data_headers = []
    return m

def readOldTypeHeaders(m, f):
    for x in range(m.Files_created):
        filename = f.read(144).decode("cp1252")
        m.Datafile_names.append(filename.rstrip("\x00"))
        h = Header()
        h.ID = f.read(8).decode("cp1252").rstrip("\x00")
        h.Type = int.from_bytes(f.read(2), "little")
        h.Version = int.from_bytes(f.read(2), "little")
        h.StartEvNo = int.from_bytes(f.read(4), "little", signed=True)
        h.LogName = f.read(80).decode("cp1252").rstrip("\x00")
        h.Mode = int.from_bytes(f.read(4), "little")
        h.Area = int.from_bytes(f.read(2), "little")
        h.Priv = int.from_bytes(f.read(2), "little")
        h.FileType = int.from_bytes(f.read(2), "little")
        h.SamplePediod = int.from_bytes(f.read(4), "little")
        h.EngUnits = f.read(8).decode("cp1252").rstrip("\x00")
        h.Format = int.from_bytes(f.read(4), "little")
        h.StartTime = datetime.fromtimestamp(int.from_bytes(f.read(4), "little"))
        h.EndTime = datetime.fromtimestamp(int.from_bytes(f.read(4), "little"))
        h.DataLength = int.from_bytes(f.read(4), "little")
        h.FilePointer = int.from_bytes(f.read(4), "little")
        h.EndEvNo = int.from_bytes(f.read(4), "little", signed=True)
        tAlign = f.read(2)
        m.Data_headers.append(h)

def readNewTypeHeaders(m, f):
    for x in range(m.Files_created):
        filename = f.read(272).decode("cp1252")
        m.Datafile_names.append(filename.rstrip("\x00"))
        h = Header()
        h.ID = f.read(8).decode("cp1252").rstrip("\x00")
        h.Type = int.from_bytes(f.read(2), "little")
        h.Version = int.from_bytes(f.read(2), "little")
        h.StartEvNo = int.from_bytes(f.read(8), "little", signed=True)
        tAlign = f.read(12)
        h.LogName = f.read(80).decode("cp1252").rstrip("\x00")
        h.Mode = int.from_bytes(f.read(4), "little")
        h.Area = int.from_bytes(f.read(2), "little")
        h.Priv = int.from_bytes(f.read(2), "little")
        h.FileType = int.from_bytes(f.read(2), "little")
        h.SamplePediod = int.from_bytes(f.read(4), "little")
        h.EngUnits = f.read(8).decode("cp1252").rstrip("\x00")
        h.Format = int.from_bytes(f.read(4), "little")
        h.StartTime = datetime(1601, 1, 1) + timedelta(microseconds=int.from_bytes(f.read(8), "little") / 10)
        h.EndTime = datetime(1601, 1, 1) + timedelta(microseconds=int.from_bytes(f.read(8), "little") / 10)
        h.DataLength = int.from_bytes(f.read(4), "little")
        h.FilePointer = int.from_bytes(f.read(4), "little")
        h.EndEvNo = int.from_bytes(f.read(8), "little", signed=True)
        tAlign = f.read(6)
        m.Data_headers.append(h)

def readOldDataHeader(f):
    h = Header()
    h.ID = f.read(8).decode("cp1252").rstrip("\x00")
    h.Type = int.from_bytes(f.read(2), "little")
    h.Version = int.from_bytes(f.read(2), "little")
    h.StartEvNo = int.from_bytes(f.read(4), "little", signed=True)
    h.LogName = f.read(80).decode("cp1252").rstrip("\x00")
    h.Mode = int.from_bytes(f.read(4), "little")
    h.Area = int.from_bytes(f.read(2), "little")
    h.Priv = int.from_bytes(f.read(2), "little")
    h.FileType = int.from_bytes(f.read(2), "little")
    h.SamplePediod = int.from_bytes(f.read(4), "little")
    h.EngUnits = f.read(8).decode("cp1252").rstrip("\x00")
    h.Format = int.from_bytes(f.read(4), "little")
    h.StartTime = datetime.fromtimestamp(int.from_bytes(f.read(4), "little"))
    h.EndTime = datetime.fromtimestamp(int.from_bytes(f.read(4), "little"))
    h.DataLength = int.from_bytes(f.read(4), "little")
    h.FilePointer = int.from_bytes(f.read(4), "little")
    h.EndEvNo = int.from_bytes(f.read(4), "little", signed=True)
    tAlign = f.read(2)
    return h

def readNewDataHeader(f):
    h = Header()
    h.ID = f.read(8).decode("cp1252").rstrip("\x00")
    h.Type = int.from_bytes(f.read(2), "little")
    h.Version = int.from_bytes(f.read(2), "little")
    h.StartEvNo = int.from_bytes(f.read(8), "little", signed=True)
    tAlign = f.read(12)
    h.LogName = f.read(80).decode("cp1252").rstrip("\x00")
    h.Mode = int.from_bytes(f.read(4), "little")
    h.Area = int.from_bytes(f.read(2), "little")
    h.Priv = int.from_bytes(f.read(2), "little")
    h.FileType = int.from_bytes(f.read(2), "little")
    h.SamplePediod = int.from_bytes(f.read(4), "little")
    h.EngUnits = f.read(8).decode("cp1252").rstrip("\x00")
    h.Format = int.from_bytes(f.read(4), "little")
    h.StartTime = datetime(1601, 1, 1) + timedelta(microseconds=int.from_bytes(f.read(8), "little") / 10)
    h.EndTime = datetime(1601, 1, 1) + timedelta(microseconds=int.from_bytes(f.read(8), "little") / 10)
    h.DataLength = int.from_bytes(f.read(4), "little")
    h.FilePointer = int.from_bytes(f.read(4), "little")
    h.EndEvNo = int.from_bytes(f.read(8), "little", signed=True)
    tAlign = f.read(6)
    return h

def examineDataFiles(m: MasterHeader):
    x = 0
    if m.Version == 5:
        type = "Type: 2 byte"
    else:
        type = "Type: 8 byte"
    print(type, "| Maximum number of files:", m.Max_nr_files, "| Files created:", m.Files_created)
    for d in m.Data_headers:
        if m.Version == 5:
            print("File:", x, m.Datafile_names[x], "| Start:", d.StartTime, "| End:", d.EndTime, "| Samples:", d.DataLength)
            x += 1
        else:
            print("File:", x, m.Datafile_names[x], "Start:", d.StartTime, "End:", d.EndTime, "| Samples:", d.DataLength)
            x += 1
    sys.exit(0)

def readScales(f):
    e = EngScale()
    e.RawZero = struct.unpack("f", f.read(4))[0]
    e.RawFull = struct.unpack("f", f.read(4))[0]
    e.EngZero = struct.unpack("f", f.read(4))[0]
    e.EngFull = struct.unpack("f", f.read(4))[0]
    return e

def calcValue(e: EngScale, meas, precision):
    v = e.EngZero + ((meas - 0) / (32000)) * (e.EngFull - e.EngZero)
    return round(v, precision)

def stripDirectories(m: MasterHeader):
    x = 0
    for d in m.Datafile_names:
        path = d.split("\\")
        file = path[-1]
        m.Datafile_names[x] = file
        x += 1

def selectDataFiles(m: MasterHeader, startTime, stopTime):
    x = 0
    data = []
    for d in m.Data_headers:
        if d.StartTime <= startTime and d.EndTime > startTime:
            data.append(x)
        elif d.StartTime < stopTime and d.EndTime > stopTime:
            data.append(x)
        elif d.StartTime >= startTime and d.EndTime <= stopTime:
            data.append(x)
        x += 1
    return data

def get_file_start_time(data_file, version):
    if not os.path.exists(data_file):
        return None
    with open(data_file, "rb") as f:
        f.read(112)  # Skip title
        f.read(16)  # Skip scales
        if version == 5:
            h = readOldDataHeader(f)
        else:
            h = readNewDataHeader(f)
        return h.StartTime

def main():
    print("Starting HST parsing...")
    args = parseArgs()
    if args.file.split(".")[-1].upper() != "HST":
        print("Check filename. Use .HST")
        sys.exit(2)

    os.makedirs(args.outdir, exist_ok=True)

    with open(args.file, "rb") as f:
        m = readMasterHeader(f)
        if m.Version == 5:
            readOldTypeHeaders(m, f)
        if m.Version == 6:
            readNewTypeHeaders(m, f)

    if args.s:
        stripDirectories(m)

    if args.e:
        examineDataFiles(m)

    if args.start and not args.stop or args.stop and not args.start:
        print("Both -start and -stop arguments should be used together.")
        sys.exit(2)
    try:
        startTime = datetime.strptime(args.start, "%Y-%m-%d") if args.start else None
        stopTime = datetime.strptime(args.stop, "%Y-%m-%d") if args.stop else None
    except Exception:
        print("Invalid date format. Use YYYY-MM-DD")
        sys.exit(0)

    if args.f:
        datalist = [args.f]
    elif startTime and stopTime:
        datalist = selectDataFiles(m, startTime, stopTime)
    else:
        datalist = list(range(m.Files_created))

    # Pre-sort datalist by StartTime of each file
    file_times = []
    for idx in datalist:
        data_file = os.path.join(os.path.dirname(args.file), m.Datafile_names[idx])
        start_time = get_file_start_time(data_file, m.Data_headers[idx].Version)
        if start_time is not None:
            file_times.append((idx, start_time))
        else:
            print(f"Warning: Could not get start time for {m.Datafile_names[idx]} - skipping sort for this file")

    # Sort by start_time
    file_times.sort(key=lambda x: x[1])
    datalist = [idx for idx, _ in file_times]

    print("Data files to process (sorted by start time):", [m.Datafile_names[i] for i in datalist])

    # *** SINGLE CSV: Append ALL files to ONE CSV ***
    base_name = os.path.splitext(os.path.basename(args.file))[0]
    output_file = os.path.join(args.outdir, f"{base_name}.csv")
    
    with open(output_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Time", "Value"])
        
        for data_idx in datalist:
            data_file = os.path.join(os.path.dirname(args.file), m.Datafile_names[data_idx])
            if not os.path.exists(data_file):
                print(f"Skipping {data_file}: File does not exist")
                continue
                
            print(f"Processing {os.path.basename(data_file)}...")
            
            with open(data_file, "rb") as f:
                f.read(112)  # Skip title
                e = readScales(f)

                if m.Data_headers[data_idx].Version == 5:
                    h = readOldDataHeader(f)
                    sp = h.SamplePediod / 1000
                    x = 0
                    while True:
                        bytes = f.read(2)
                        if not bytes:
                            break
                        value = int.from_bytes(bytes, "little", signed=True)
                        if args.d and (value == -32001 or value == -32002):
                            x += 1
                            continue
                        calc_value = calcValue(e, value, args.p)
                        realtime = h.StartTime + timedelta(seconds=sp * x)
                        
                        if startTime and stopTime:
                            if realtime >= startTime and realtime <= stopTime:
                                writer.writerow([realtime, calc_value])
                        else:
                            writer.writerow([realtime, calc_value])
                        x += 1
                else:  # 8-byte version
                    h = readNewDataHeader(f)
                    x = 0
                    while True:
                        bytes = f.read(8)
                        if not bytes:
                            break
                        value = struct.unpack("@d", bytes)[0]
                        if args.d and math.isnan(value):
                            x += 1
                            continue
                        realtime = h.StartTime + timedelta(microseconds=h.SamplePediod * 1000 * x)
                        rounded_value = round(value, args.p)
                        
                        if startTime and stopTime:
                            if realtime >= startTime and realtime <= stopTime:
                                writer.writerow([realtime, rounded_value])
                        else:
                            writer.writerow([realtime, rounded_value])
                        x += 1
                        
    print(f"✓ Combined CSV saved: {output_file}")

if __name__ == "__main__":
    main()