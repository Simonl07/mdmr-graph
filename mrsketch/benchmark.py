from . import Graph, StateDescriptor, NDPath, Path
from runstats import Statistics
from datetime import datetime
import time
import pandas as pd
from tqdm import tqdm
import pygeohash as pgh

data = pd.read_csv('./mrsketch/namanl_218_20141212_0600_000.grb.bz2.tdv', delimiter=r'\s+', index_col=False)

total_records = 10000

records = []

c = 0
for index, record in tqdm(data.iterrows()):
    if c == total_records:
        break
    c += 1
    records.append({
        'UTC_TIMESTAMP': int(getattr(record, '1_time')),
        'LATITUDE': getattr(record, '2_lat'),
        'LONGITUDE': getattr(record, '3_lon'),
        'albedo_surface': getattr(record, 'albedo_surface')
    })

statistics = StateDescriptor(
    constructor=lambda: Statistics(),
    updater=lambda x, s: s.push(x['albedo_surface']),
    merger=lambda s1, s2: s1 + s2,
    serializer=lambda s: s.get_state(),
    deserializer=lambda s: Statistics.fromstate(s)
)


def spacetime_extract(x):
    d = datetime.utcfromtimestamp(x['UTC_TIMESTAMP'] / 1000)
    gh = pgh.encode(x['LATITUDE'], x['LONGITUDE'])
    return {
        'Time': [d.year, d.month, d.day, d.hour],
        'Space': [g for g in gh[:6]]
    }

g = Graph(
    state_descriptors={
        'statistics': statistics
    },
    path_extractor=spacetime_extract
)

print('single thread')
start = time.time()
for record in tqdm(records):
    g.push(record)
end = time.time()
print(end - start)
s = g.get({'Time': [2014], 'Space': []})
print(s[0])
print(len(s[0]))
