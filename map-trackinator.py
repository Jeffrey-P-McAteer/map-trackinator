#!/usr/bin/env python

# Python builtins
import os
import sys
import subprocess
import shutil
import importlib
import asyncio
import ssl
import traceback
import json
import random
import time
import io
import base64


# Utility method to wrap imports with a call to pip to install first.
# > "100% idiot-proof!" -- guy on street selling rusty dependency chains.
def import_maybe_installing_with_pip(import_name, pkg_name=None):
  if pkg_name is None:
    pkg_name = import_name # 90% of all python packages share their name with their module
  pkg_spec = importlib.util.find_spec(import_name)
  install_cmd = []
  if pkg_spec is None:
    # package missing, install via pip to user prefix!
    print('Attempting to install module {} (package {}) with pip...'.format(import_name, pkg_name))
    install_cmd = [sys.executable, '-m', 'pip', 'install', '--user', pkg_name]
    subprocess.run(install_cmd, check=False)
  pkg_spec = importlib.util.find_spec(import_name)
  if pkg_spec is None:
    raise Exception('Cannot find module {}, attempted to install {} via pip: {}'.format(import_name, pkg_name, ' '.join(install_cmd) ))
  
  return importlib.import_module(import_name)

# 3rd-party libs
aiohttp = import_maybe_installing_with_pip('aiohttp')
import aiohttp
import aiohttp.web

PIL = import_maybe_installing_with_pip('PIL', 'Pillow')
#import PIL.Image
from PIL import Image, ImageDraw

xyzservices = import_maybe_installing_with_pip('xyzservices')

contextily = import_maybe_installing_with_pip('contextily')
import contextily
mercantile = import_maybe_installing_with_pip('mercantile')
import mercantile
numpy = import_maybe_installing_with_pip('numpy')
import numpy

# Globals
map_state_csv = os.path.join('out', 'positions.csv')
all_websockets = []

def c(*args):
  subprocess.run([x for x in args if x is not None], check=True)

def maybe(fun):
  try:
    return fun()
  except:
    traceback.print_exc()
    return None

async def maybe_await(fun, on_exception=None):
  try:
    return await fun()
  except:
    traceback.print_exc()
    if on_exception != None:
      return on_exception()
    return None


def j(*file_path_parts):
  return os.path.join(*[x for x in file_path_parts if x is not None])

def e(*file_path_parts):
  return os.path.exists(j(*file_path_parts))

def get_ssl_cert_and_key_or_generate():
  ssl_dir = 'ssl'
  if not e(ssl_dir):
    os.makedirs(ssl_dir)
  
  key_file = j(ssl_dir, 'server.key')
  cert_file = j(ssl_dir, 'server.crt')

  if e(key_file) and e(cert_file):
    return cert_file, key_file
  else:
    if e(key_file):
      os.remove(key_file)
    if e(cert_file):
      os.remove(cert_file)
  
  if not shutil.which('openssl'):
    raise Exception('Cannot find the tool "openssl", please install this so we can generate ssl certificates for our servers! Alternatively, manually create the files {} and {}.'.format(cert_file, key_file))

  generate_cmd = ['openssl', 'req', '-x509', '-sha256', '-nodes', '-days', '28', '-newkey', 'rsa:2048', '-keyout', key_file, '-out', cert_file]
  subprocess.run(generate_cmd, check=True)

  return cert_file, key_file

def get_local_ip():
    import socket
    """Try to determine the local IP address of the machine."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Use Google Public DNS server to determine own IP
        sock.connect(('8.8.8.8', 80))

        return sock.getsockname()[0]
    except socket.error:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return '127.0.0.1'
    finally:
        sock.close() 

def save_pos_rep(name, lat, lon):
  timestamp = int(time.time())
  if not os.path.exists(map_state_csv):
    with open(map_state_csv, 'w') as fd:
      fd.write('')
  with open(map_state_csv, 'a') as fd:
    fd.write('{},{},{},{}\n'.format(name, timestamp, lat, lon))

def get_pos_reps():
  if not os.path.exists(map_state_csv):
    return []
  pos_rep_s = ''  
  with open(map_state_csv, 'r') as fd:
    pos_rep_s = fd.read()
  pos_rep_list = []
  for line in pos_rep_s.splitlines(False):
    if len(line) < 2:
      continue
    try:
      columns = line.split(',')
      pos_rep_list.append({
        'name': str(columns[0]),
        'timestamp': int(columns[1]),
        'lat': float(columns[2]),
        'lon': float(columns[3]),
      })
    except:
      traceback.print_exc()
  return pos_rep_list

async def http_file_req_handler(req):
  # Normalize & trim path
  path = req.path.lower()
  while path.startswith('/'):
    path = path[1:]

  if len(path) < 1:
    path = 'index.html'

  possible_www_f = j('www', path)

  if e(possible_www_f):
    print('Returning {}'.format(possible_www_f))
    return aiohttp.web.FileResponse(possible_www_f)

  print('Returning 404 for {}'.format(req.path))
  return aiohttp.web.HTTPNotFound()

async def http_pos_update_req_handler(req):
  name = 'UNK'
  try:
    name = str(req.match_info['name']).strip()
    lat = float(req.match_info['lat'])
    lon = float(req.match_info['lon'])

    save_pos_rep(name, lat, lon)
    print('Saved {} at {},{}'.format(name, lat, lon))

  except:
    traceback.print_exc()
    return aiohttp.web.Response(text='Error: {}'.format( traceback.format_exc() ))

  return aiohttp.web.Response(text='Position recieved, thanks {}!'.format(name))

async def ws_req_handler(req):
  global all_websockets

  peername = req.transport.get_extra_info('peername')
  host = 'unk'
  if peername is not None:
    try:
      host, port = peername
    except:
      pass

  print('ws req from {}'.format(host))

  ws = aiohttp.web.WebSocketResponse()
  await ws.prepare(req)

  all_websockets.append(ws)

  async for msg in ws:
    if msg.type == aiohttp.WSMsgType.TEXT:
      print('WS From {}: {}'.format(host, msg.data))

      try:
        # Pull position data out + use it
        data = json.loads(msg.data)
        print('data={}'.format(data))

        if 'new_icon' in data:

          icon_name = data['name']

          # Parse base64 string, save to out/{name}.png
          icon_base64 = data['new_icon']
          # Add padding b/c python's decoder is super strict
          icon_base64 += "=" * ((4 - len(icon_base64) % 4) % 4)

          image_bytes = base64.b64decode(icon_base64)
          image_file_obj = io.BytesIO(image_bytes)
          image_file_obj.seek(0)
          #image_o = PIL.Image.open(image_file_obj)
          image_o = Image.open(image_file_obj)

          os.makedirs('out', exist_ok=True)
          image_out_path = os.path.join('out', '{}.png'.format(icon_name) )
          image_o.save(image_out_path, 'PNG')

        else:
          save_pos_rep(data['name'], data['lat'], data['lon'])

      except:
        traceback.print_exc()
      
    elif msg.type == aiohttp.WSMsgType.ERROR:
      print('ws connection closed with exception {}'.format(ws.exception()))

  all_websockets.remove(ws)

  return ws

def bound(value, _min, _max):
  if value < _min:
    return bound(value + (_max - _min), _min, _max)
  if value > _max:
    return bound(value - (_max - _min), _min, _max)
  return value

# https://github.com/geopandas/contextily/blob/37d33ed33bed08b5ae6a79891a8a14cd53dd93d8/contextily/tile.py#L234
async def trackinator_bounds2img(min_lon, min_lat, max_lon, max_lat):
  source = xyzservices.TileProvider(
    name='OSM',
    url='https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution='(C) OSM',
  )
  zoom = 99
  max_zoom_lvl = 19
  while zoom > max_zoom_lvl:
    zoom = contextily.tile._calculate_zoom(min_lon, min_lat, max_lon, max_lat)
    zoom = contextily.tile._validate_zoom(zoom, source, auto=True)
    if zoom > max_zoom_lvl:
      # zoom min/max lat/lon out a bit
      lat_scale = max_lat - min_lat
      lon_scale = max_lon - min_lon
      print(f'Zooming out lat_scale={lat_scale} lon_scale={lon_scale} min_lat={min_lat} max_lat={max_lat} min_lon={min_lon} max_lon={max_lon}')
      zoom_out_fraction = 0.10
      min_lat -= zoom_out_fraction * lat_scale
      max_lat += zoom_out_fraction * lat_scale
      min_lon -= zoom_out_fraction * lon_scale
      max_lon += zoom_out_fraction * lon_scale

  
  tiles = []
  arrays = []
  for tile in mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [zoom]):
    tile_url = source.build_url(x=tile.x, y=tile.y, z=tile.z)
    #print(f'TODO fetch tile_url={tile_url}')
    image = None
    while image is None:
      try:
        cache_file = os.path.join('out', '_{z}_{x}_{y}_'.format(x=tile.x, y=tile.y, z=tile.z)+( abs(hash(tile_url)).to_bytes(8,'big').hex() )+'.png'  )
        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 128:
          with open(cache_file, 'rb') as image_stream:
            image_o = Image.open(image_stream).convert("RGBA")
            image = numpy.asarray(image_o)
            image_o.close()

        else:
          async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=9)) as session:
            async with session.get(tile_url, headers={'user-agent': 'Map-Trackinator v0 (https://github.com/Jeffrey-P-McAteer/map-trackinator)'}) as resp:
              
              resp_bytes = await resp.read()

              if resp.status != 200:
                print(f'Read {len(resp_bytes)} bytes, resp.status={resp.status}')
                print('')
                print(resp_bytes.decode('utf-8'))
                print('')
                image = 'http error'

              with io.BytesIO(resp_bytes) as image_stream:
                image_o = Image.open(image_stream).convert("RGBA")
                image = numpy.asarray(image_o)
                image_o.save(cache_file, 'PNG')
                image_o.close()

      except:
        traceback.print_exc()
        time.sleep(1)
      
      if image is None or str(image) == 'http error':
        print('Re-trying {}'.format(tile_url))

    tiles.append(tile)
    arrays.append(image)

  merged, extent = contextily.tile._merge_tiles(tiles, arrays)
  # lon/lat extent --> Spheric Mercator
  west, south, east, north = extent
  left, bottom = mercantile.xy(west, south)
  right, top = mercantile.xy(east, north)
  extent = left, right, bottom, top
  return merged, extent

async def re_render_map():
  map_png = os.path.join('out', 'map.png')

  pos_reps = get_pos_reps()
  min_lat = 999.0
  max_lat = -999.0
  min_lon = 999.0
  max_lon = -999.0
  for rep in pos_reps:
    if rep['lat'] < min_lat:
      min_lat = rep['lat']
    if rep['lat'] > max_lat:
      max_lat = rep['lat']
    if rep['lon'] < min_lon:
      min_lon = rep['lon']
    if rep['lon'] > max_lon:
      max_lon = rep['lon']
  
  # Bound these a little
  lat_scale = max_lat - min_lat
  lon_scale = max_lon - min_lon

  #print(f'ORIG lat_scale={lat_scale} lon_scale={lon_scale} min_lat={min_lat} max_lat={max_lat} min_lon={min_lon} max_lon={max_lon}')

  zoom_out_fraction = 0.10
  min_lat -= zoom_out_fraction * lat_scale
  max_lat += zoom_out_fraction * lat_scale
  min_lon -= zoom_out_fraction * lon_scale
  max_lon += zoom_out_fraction * lon_scale

  min_lat = bound(min_lat, -90.0, 90.0)
  max_lat = bound(max_lat, -90.0, 90.0)
  min_lon = bound(min_lon, -180.0, 180.0)
  max_lon = bound(max_lon, -180.0, 180.0)
  
  print(f'lat_scale={lat_scale} lon_scale={lon_scale} min_lat={min_lat} max_lat={max_lat} min_lon={min_lon} max_lon={max_lon}')

  img, ext = await trackinator_bounds2img(
    min_lon, # West
    min_lat, # South
    max_lon, # East
    max_lat, # North
  )

  img_o = Image.fromarray(img, 'RGBA')
  img_w, img_h = img_o.size
  
  # Define lat,lon -> y,x translator so we can draw images & lines on top of things relative to the image
  def lat_lon_2_xy(lat, lon):
    return (
      int( ((lon - min_lon) / lon_scale) * img_w ),
      int( ((lat - min_lat) / lat_scale) * img_h )
    )

  # Grap each name, pos_name_locations[x] is x's (lat, lon) locations from oldest -> newest
  pos_name_locations = {}
  for rep in pos_reps:
    if not rep['name'] in pos_name_locations:
      pos_name_locations[ rep['name'] ] = []
    pos_name_locations[ rep['name'] ].append(
      ( rep['lat'], rep['lon'] )
    )

  img_od = ImageDraw.Draw(img_o)
  for name, coords in pos_name_locations.items():
    xy_coords = [lat_lon_2_xy(lat, lon) for lat,lon in coords]
    #print(f'{name} line coords = {xy_coords}')
    img_od.line(
      xy_coords,
      width=1, fill=(250, 20, 20)
    )
    # And put name at last coordinate
    last_xy = xy_coords[-1]
    img_od.text(
      last_xy, str(name),
      fill=(20, 20, 250),
      align='center',
    )


  img_o.save(map_png)


async def http_map_req_handler(req):
  map_png = os.path.join('out', 'map.png')
  
  # If map is old, re-render
  if not os.path.exists(map_png) or int(time.time()) - os.path.getmtime(map_png) > 300:
    re_render_map()

  # Return file 
  return aiohttp.web.FileResponse(map_png)

async def start_background_tasks(server):
  loop = asyncio.get_event_loop()
  task = loop.create_task(render_task())

async def render_task():
  last_num_positions = 0
  while True:
    try:
      this_num_positions = len( get_pos_reps() )
      if this_num_positions != last_num_positions:
        await re_render_map()
        last_num_positions = this_num_positions
    except:
      traceback.print_exc()

    await asyncio.sleep(30)


def main(args=sys.argv):
  use_ssl = False
  # prep work to avoid re-doing it later
  os.makedirs(os.path.dirname(map_state_csv), exist_ok=True)

  cert_file, key_file = (None, None)
  if use_ssl:
    cert_file, key_file = get_ssl_cert_and_key_or_generate()

  server = aiohttp.web.Application()

  server.add_routes([
    aiohttp.web.get('/', http_file_req_handler),
    aiohttp.web.get('/index.html', http_file_req_handler),
    aiohttp.web.get('/ws', ws_req_handler), # Old, do not use
    aiohttp.web.get('/pos/{name}/{lat}/{lon}', http_pos_update_req_handler),
    aiohttp.web.get('/map', http_map_req_handler),
  ])

  server.on_startup.append(start_background_tasks)

  ssl_ctx = None
  if use_ssl:
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(cert_file, key_file)

  port = int(os.environ.get('PORT', '8081'))
  server_lan_url = '{}://{}:{}/'.format('https' if use_ssl else 'http', get_local_ip(), port)
  
  if shutil.which('sh'):
    subprocess.Popen([
      'sh', '-c', 'sleep 0.5 ; curl -vk {server_lan_url}map >/dev/null 2>/dev/null '.format(server_lan_url=server_lan_url)
    ])

  print('Your LAN host is'.format(server_lan_url))

  if use_ssl:
    aiohttp.web.run_app(server, ssl_context=ssl_ctx, port=port)
  else:
    aiohttp.web.run_app(server, port=port)


if __name__ == '__main__':
  main()

