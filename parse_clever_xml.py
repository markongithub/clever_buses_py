import os
import re
import sys
from xml.etree.ElementTree import parse, ParseError
from collections import defaultdict
import pandas as pd
from datetime import datetime
import gc

# No I can't use read_xml because it doesn't handle "N/A" correctly.
def etree_to_dict(t):
    d = {t.tag: {} if t.attrib else None}
    children = list(t)
    if children:
        dd = defaultdict(list)
        for dc in map(etree_to_dict, children):
            for k, v in dc.items():
                dd[k].append(v)
        d = {t.tag: {k: v[0] if len(v) == 1 else v
                     for k, v in dd.items()}}
    if t.attrib:
        d[t.tag].update(('@' + k, v)
                        for k, v in t.attrib.items())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
              d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d

example_file = './buses2022-03-01T01:30:04.xml'
relevant_keys = ['fs', 'dd', 'pid', 'run', 'bid', 'id', 'lat', 'lon']

def time_from_filename(filename):
  date_str = re.search('buses(.+)\.xml', filename).group(1)
  return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S')

def bus_dicts_from_file(filename):
  doc = parse(open(filename))
  retrieved_at = time_from_filename(filename)
  bus_dicts = []
  for bus in doc.findall('bus'):
    old_dict = etree_to_dict(bus)['bus']
    new_dict = { my_key: old_dict[my_key] for my_key in relevant_keys }
    new_dict['retrieved_at'] = retrieved_at
    bus_dicts.append(new_dict)
  return bus_dicts

def read_parquet_if_exists(filename):
  if os.path.exists(filename):
    return pd.read_parquet(filename)
  else:
    return pd.DataFrame()

old_df = read_parquet_if_exists(sys.argv[1])
rows = []
skipped_files = 0
processed_files = 0
for bus_file in sys.argv[2:]:
  try:
    rows += bus_dicts_from_file(bus_file)
    processed_files += 1
  except ParseError:
    print(f"{bus_file} seems bad. Skipping that one.")
    skipped_files += 1
new_df = pd.DataFrame(rows)
final_df = pd.concat([old_df, new_df])
old_df=pd.DataFrame()
new_df=pd.DataFrame()
gc.collect()
print("Writing out final parquet file...")
print(final_df.info())
final_df.to_parquet(sys.argv[1])

print("Confirming that written file is readable...")
del[[final_df]]
gc.collect()
is_parquet_valid = pd.read_parquet(sys.argv[1])

print(f"{processed_files} processed, {skipped_files} skipped")
