import os
import glob
import pandas as pd
import logging
import json
import gzip
import shutil
import time
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count, freeze_support
from tqdm import tqdm

# Load config from JSON
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if not os.path.exists(config_path):
        print("config.json not found!")
        exit(1)
    with open(config_path, 'r') as f:
        return json.load(f)

CONFIG = load_config()

# From config
DEFAULT_INPUT_FOLDER = CONFIG['default_input_folder']
TRENDCONVERT_PATH = CONFIG['trendconvert_path']
SHARED_OUTPUT = CONFIG['shared_output']
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), CONFIG['progress_file'])
LOG_DIR = os.path.join(os.path.dirname(__file__), CONFIG.get('log_dir', '.'))
TEMP_DIR = os.path.join(os.path.dirname(__file__), CONFIG['temp_dir'])
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_progress(processed):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(list(processed), f)

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

def get_total_size(folder):
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total / (1024 * 1024 * 1024)  # GB

def process_hst_to_csv(hst_file):
    start_time = time.perf_counter()
    hst_size = os.path.getsize(hst_file) / (1024 * 1024)  # MB
    logging.info(f"Processing {os.path.basename(hst_file)} (Size: {hst_size:.2f} MB)")
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", TEMP_DIR]
    for attempt in range(CONFIG['max_retries']):
        try:
            conv_start = time.perf_counter()
            result = subprocess.run(cmd, capture_output=False, text=True, check=True)
            conv_time = time.perf_counter() - conv_start
            logging.info(f"  ✓ Conversion time: {conv_time:.2f}s")
            
            base_name = os.path.splitext(os.path.basename(hst_file))[0]
            csv_temp = os.path.join(TEMP_DIR, f"{base_name}.csv")
            if os.path.exists(csv_temp):
                rename_start = time.perf_counter()
                df = pd.read_csv(csv_temp)
                df.rename(columns={'Time': 'Timestamp'}, inplace=True)
                df.to_csv(csv_temp, index=False)
                rename_time = time.perf_counter() - rename_start
                csv_size = os.path.getsize(csv_temp) / (1024 * 1024)  # MB
                
                comp_start = time.perf_counter()
                gz_temp = csv_temp + '.gz'
                with open(csv_temp, 'rb') as f_in, gzip.open(gz_temp, 'wb', compresslevel=CONFIG['gzip_level']) as f_out:
                    shutil.copyfileobj(f_in, f_out)
                comp_time = time.perf_counter() - comp_start
                gz_size = os.path.getsize(gz_temp) / (1024 * 1024)  # MB
                logging.info(f"  ✓ Compressed (CSV: {csv_size:.2f}MB → gz: {gz_size:.2f}MB, time: {comp_time:.2f}s)")
                
                trans_start = time.perf_counter()
                gz_shared = os.path.join(SHARED_OUTPUT, os.path.basename(gz_temp))
                shutil.copy(gz_temp, gz_shared)
                trans_time = time.perf_counter() - trans_start
                logging.info(f"  ✓ Transferred (time: {trans_time:.2f}s)")
                
                os.remove(csv_temp)
                os.remove(gz_temp)
                logging.info("  ✓ Cleaned local temp files")
                
                elapsed = time.perf_counter() - start_time
                logging.info(f"  Total time: {elapsed:.2f}s")
                return gz_shared
            return None
        except Exception as e:
            logging.exception(f"Attempt {attempt+1} failed for {hst_file}: {e}")
    logging.error(f"✗ Failed {os.path.basename(hst_file)} after {CONFIG['max_retries']} attempts")
    return None

if __name__ == '__main__':
    freeze_support()
    
    # Unique log file
    now_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    input_folders = get_input_folders()  # Get folders first for title
    first_folder_name = os.path.basename(input_folders[0]).replace(' ', '_') if input_folders else "no_folder"
    log_file = os.path.join(LOG_DIR, f"wrapper_{first_folder_name}_{now_str}.log")
    logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger().handlers[0].baseFilename = log_file  # Update handler
    
    logging.info("🚀 Starting HST to CSV on VM #1 (immediate compressed transfer to VM #2)")
    
    # User prompts
    max_processes = int(get_user_input(f"Max processor cores (default {cpu_count() - 2}): ", cpu_count() - 2))
    batch_size = int(get_user_input("Max HSTs per batch (suggest 200 for large data): ", 200))
    
    processed = load_progress()
    
    # Collect tasks, skip processed or if gz exists on shared; log total size
    tasks = []
    total_size_gb = 0
    for input_folder in input_folders:
        logging.info(f"\nProcessing folder: {input_folder}")
        folder_size_gb = get_total_size(input_folder)
        total_size_gb += folder_size_gb
        logging.info(f"  Folder size: {folder_size_gb:.2f} GB")
        hst_files = glob.glob(os.path.join(input_folder, "*.hst"))
        logging.info(f"📋 Found {len(hst_files)} HST files")
        for hst in hst_files:
            base_name = os.path.splitext(os.path.basename(hst))[0]
            gz_shared = os.path.join(SHARED_OUTPUT, f"{base_name}.csv.gz")
            if hst not in processed and not os.path.exists(gz_shared):
                tasks.append(hst)
    
    logging.info(f"Total data to process: {total_size_gb:.2f} GB")
    logging.info(f"Estimated time (based on 18.5GB/80min): ~{(total_size_gb / 18.5 * 80 / 60):.1f} hours")
    
    # Process in batches
    csv_files = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        logging.info(f"\nParallel processing batch {i//batch_size + 1} ({len(batch)} files)...")
        with Pool(processes=max_processes) as pool:
            batch_csvs = list(tqdm(pool.imap(process_hst_to_csv, batch), total=len(batch), desc="Converting HSTs"))
        csv_files.extend([c for c in batch_csvs if c])
        # Update progress
        processed.update(batch)
        save_progress(processed)
    
    logging.info("\n🎉 All CSVs transferred immediately to VM #2 shared folder. Run inserter on VM #2.")