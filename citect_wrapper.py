import os
import glob
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count, freeze_support
from tqdm import tqdm

# ========== VM #1 CONFIGURATION ==========
# Local paths on VM #1
DEFAULT_INPUT_FOLDER = r"D:\khayyamian\Hamid\data"  # HST files location on VM #1
TRENDCONVERT_PATH = r"D:\khayyamian\Hamid\trendconvert\trendconvert.py"

# Remote paths (VM #2)
REMOTE_CSV_FOLDER = r"Y:\\"  # Mapped share: \\192.168.11.32\ElahiTest
INFLUX_URL = "http://localhost:8086"  # Remote InfluxDB on VM #2
INFLUX_TOKEN = "Q0Zo8Wcc_4Tn3apXQBjCv2ME7GVV9LPLURByqbDuZR2_orPMxRA1reNsiKlJFYdCkadgn7hZ4LiGe2VDERq5TA=="
INFLUX_ORG = "SS"
INFLUX_BUCKET = "Elahi_Test"

# Local temp folder for CSVs (before network copy)
LOCAL_TEMP_CSV = r"D:\temp_csvs"

def get_user_input(prompt, default=None):
    user_input = input(prompt).strip()
    return user_input if user_input else default

def get_input_folders():
    use_default = get_user_input(f"Use default input folder ({DEFAULT_INPUT_FOLDER})? (y/n): ", "y").lower()
    if use_default == 'y':
        return [DEFAULT_INPUT_FOLDER]
    
    input_type = get_user_input("Enter 's' for single folder or 't' for text file with multiple folders: ").lower()
    if input_type == 's':
        folder = get_user_input("Enter the input folder path: ")
        return [folder]
    elif input_type == 't':
        text_file = get_user_input("Enter the text file path containing folder paths: ")
        with open(text_file, 'r') as f:
            folders = [line.strip() for line in f if line.strip()]
        return folders
    else:
        print("Invalid choice. Exiting.")
        exit(1)

def process_hst_to_csv(args):
    """Process HST to CSV locally on VM #1, then copy to VM #2"""
    hst_file, local_output = args
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", local_output]
    try:
        subprocess.run(cmd, capture_output=False, text=True, check=True)
        
        base_name = os.path.splitext(os.path.basename(hst_file))[0]
        csv_file = os.path.join(local_output, f"{base_name}.csv")
        
        if os.path.exists(csv_file):
            # Rename 'Time' to 'Timestamp'
            df = pd.read_csv(csv_file)
            df.rename(columns={'Time': 'Timestamp'}, inplace=True)
            df.to_csv(csv_file, index=False)
            
            size_mb = os.path.getsize(csv_file) / 1024 / 1024
            print(f"✅ Processed {os.path.basename(hst_file)} → {size_mb:.1f} MB CSV")
            
            return csv_file
        return None
    except subprocess.CalledProcessError as e:
        print(f"❌ ERROR {os.path.basename(hst_file)}: {e}")
        return None

def copy_csv_to_remote(local_csv, remote_folder):
    """Copy CSV from VM #1 local storage to VM #2 network share"""
    try:
        import shutil
        remote_path = os.path.join(remote_folder, os.path.basename(local_csv))
        print(f"  📤 Copying to VM #2: {os.path.basename(local_csv)}...", end=" ")
        shutil.copy2(local_csv, remote_path)
        size_mb = os.path.getsize(remote_path) / 1024 / 1024
        print(f"✅ ({size_mb:.1f} MB)")
        return remote_path
    except Exception as e:
        print(f"❌ Copy failed: {e}")
        return None

def create_bucket_if_not_exists(client, bucket_name):
    buckets_api = client.buckets_api()
    buckets = buckets_api.find_buckets(name=bucket_name)
    if len(buckets.buckets) == 0:
        buckets_api.create_bucket(bucket_name=bucket_name, org=INFLUX_ORG)
        print(f"  ✅ Created new bucket: {bucket_name}")

def insert_csv_to_influx(csv_file, hst_base_name):
    """Insert CSV to remote InfluxDB on VM #2"""
    try:
        print(f"\n📊 Inserting {os.path.basename(csv_file)} to InfluxDB (VM #2)...")
        df = pd.read_csv(csv_file, parse_dates=['Timestamp'])
        print(f"  Loaded {len(df):,} rows")
        
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        create_bucket_if_not_exists(client, INFLUX_BUCKET)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        
        points = []
        batch_size = 5000
        total_written = 0
        
        for i, (_, row) in tqdm(enumerate(df.iterrows()), total=len(df), desc="  Inserting"):
            point = Point(hst_base_name).field("value", float(row['Value'])).tag("tag", hst_base_name).time(row['Timestamp'], WritePrecision.S)
            points.append(point)
            if len(points) >= batch_size:
                write_api.write(bucket=INFLUX_BUCKET, record=points)
                total_written += len(points)
                points = []
        
        if points:
            write_api.write(bucket=INFLUX_BUCKET, record=points)
            total_written += len(points)
        
        client.close()
        print(f"  ✅ Inserted {total_written:,} points to InfluxDB")
        
    except Exception as e:
        print(f"❌ Error inserting {csv_file}: {e}")

if __name__ == '__main__':
    freeze_support()
    
    print("=" * 60)
    print("🚀 VM #1 → VM #2 Pipeline")
    print("=" * 60)
    print(f"📍 Processing on: VM #1 (192.168.11.110, 22 cores)")
    print(f"📍 CSV destination: {REMOTE_CSV_FOLDER} (VM #2)")
    print(f"📍 InfluxDB: {INFLUX_URL} (VM #2)")
    print("=" * 60)
    
    # Check network share accessibility
    if not os.path.exists(REMOTE_CSV_FOLDER):
        print(f"❌ ERROR: Cannot access remote CSV folder: {REMOTE_CSV_FOLDER}")
        print("   Please map network share: net use Y: \\\\192.168.11.32\\ElahiTest")
        exit(1)
    
    # User prompts for input folders
    input_folders = get_input_folders()
    
    # Create local temp folder
    os.makedirs(LOCAL_TEMP_CSV, exist_ok=True)
    
    # Collect all HST files
    all_hst_files = []
    for input_folder in input_folders:
        print(f"\n📂 Scanning folder: {input_folder}")
        hst_files = glob.glob(os.path.join(input_folder, "*.hst"))
        print(f"   Found {len(hst_files)} HST files")
        all_hst_files.extend(hst_files)
    
    if not all_hst_files:
        print("❌ No HST files found. Exiting.")
        exit(0)
    
    print(f"\n📋 Total HST files to process: {len(all_hst_files)}")
    
    # ========== STAGE 1: HST → CSV (Parallel on VM #1) ==========
    print(f"\n{'='*60}")
    print("STAGE 1: Converting HST → CSV (using 21 cores on VM #1)")
    print(f"{'='*60}")
    
    tasks = [(hst, LOCAL_TEMP_CSV) for hst in all_hst_files]
    with Pool(processes=cpu_count() - 1) as pool:  # 21 cores
        csv_files = list(tqdm(pool.imap(process_hst_to_csv, tasks), total=len(tasks), desc="Converting HSTs"))
    csv_files = [c for c in csv_files if c]
    
    print(f"\n✅ Stage 1 complete: {len(csv_files)} CSVs generated locally")
    
    # ========== STAGE 2: Copy CSVs to VM #2 ==========
    print(f"\n{'='*60}")
    print("STAGE 2: Copying CSVs to VM #2 (network transfer)")
    print(f"{'='*60}")
    
    remote_csv_files = []
    for csv_file in tqdm(csv_files, desc="Copying to VM #2"):
        remote_path = copy_csv_to_remote(csv_file, REMOTE_CSV_FOLDER)
        if remote_path:
            remote_csv_files.append((remote_path, os.path.splitext(os.path.basename(csv_file))[0]))
    
    print(f"\n✅ Stage 2 complete: {len(remote_csv_files)} CSVs copied to VM #2")
    
    # ========== STAGE 3: Insert to InfluxDB ==========
    print(f"\n{'='*60}")
    print("STAGE 3: Inserting CSVs to InfluxDB on VM #2")
    print(f"{'='*60}")
    
    for remote_csv, hst_base in remote_csv_files:
        insert_csv_to_influx(remote_csv, hst_base)
    
    # ========== CLEANUP ==========
    cleanup = get_user_input(f"\n🗑️  Delete local temp CSVs from {LOCAL_TEMP_CSV}? (y/n): ", "y").lower()
    if cleanup == 'y':
        for csv_file in csv_files:
            if os.path.exists(csv_file):
                os.remove(csv_file)
        print(f"✅ Cleaned up {len(csv_files)} local temp CSVs")
    
    print("\n" + "=" * 60)
    print("🎉 PIPELINE COMPLETE!")
    print("=" * 60)
    print(f"📊 Processed: {len(all_hst_files)} HST files")
    print(f"📁 CSVs saved on VM #2: {REMOTE_CSV_FOLDER}")
    print(f"💾 InfluxDB data: {INFLUX_URL}")
    print("=" * 60)