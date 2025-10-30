import os
import glob
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
from tqdm import tqdm

# Config
SHARED_FOLDER = r'C:\Users\Administrator\Desktop\Elahi Test'  # Local on VM #2
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "JUwfBhDMbrwp7Ygz9SN58z_4xQisVrnABtP_8YEGz6KJ-fopMAbAM5O83UBdEThpB-4F38h3AYDaPVKSmd5SjA=="
INFLUX_ORG = "khayyamian"
INFLUX_BUCKET = "PGDP"

def insert_csv_to_influx(csv_file):
    try:
        base_name = os.path.splitext(os.path.basename(csv_file))[0]
        print(f"\n→ Inserting {base_name}.csv to InfluxDB...")
        df = pd.read_csv(csv_file, parse_dates=['Timestamp'])
        print(f"  Loaded {len(df):,} rows")
        
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        
        points = []
        batch_size = 5000
        total_written = 0
        
        for i, (_, row) in tqdm(enumerate(df.iterrows()), total=len(df), desc="Inserting data"):
            point = Point(base_name).field("value", float(row['Value'])).time(row['Timestamp'], WritePrecision.S)
            points.append(point)
            if len(points) >= batch_size:
                write_api.write(bucket=INFLUX_BUCKET, record=points)
                total_written += len(points)
                points = []
        
        if points:
            write_api.write(bucket=INFLUX_BUCKET, record=points)
            total_written += len(points)
        
        client.close()
        print(f"  ✓ Inserted {total_written:,} points (measurement: {base_name})")
        
        # Optional: Delete CSV after insert
        # os.remove(csv_file)
        # print(f"  ✓ Deleted {base_name}.csv after insert")
        
    except Exception as e:
        print(f"✗ Error inserting {csv_file}: {e}")

if __name__ == '__main__':
    print("🚀 Starting CSV to InfluxDB Insertion on VM #2")
    
    csv_files = glob.glob(os.path.join(SHARED_FOLDER, "*.csv"))
    print(f"📋 Found {len(csv_files)} CSVs in shared folder")
    
    for csv_file in csv_files:
        insert_csv_to_influx(csv_file)
    
    print("\n🎉 Insertion COMPLETE!")