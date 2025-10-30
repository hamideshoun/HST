from influxdb_client import InfluxDBClient
client = InfluxDBClient(url='http://localhost:8086', token='Q0Zo8Wcc_4Tn3apXQBjCv2ME7GVV9LPLURByqbDuZR2_orPMxRA1reNsiKlJFYdCkadgn7hZ4LiGe2VDERq5TA==', org='khayyamian')

print('=== FIRST 10 POINTS ===')
query = 'from(bucket: "citect trends") |> range(start: -1d) |> limit(n:10)'
result = client.query_api().query(query)

for table in result:
    for record in table.records:
        print(f'{record.get_time()} | {record.values["_measurement"]} | {record.values["_field"]} | {record.values["_value"]:.2f}')

client.close()