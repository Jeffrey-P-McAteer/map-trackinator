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
import aiohttp.web

PIL = import_maybe_installing_with_pip('PIL', 'Pillow')
#import PIL.Image
from PIL import Image

map_machine = import_maybe_installing_with_pip('map_machine', 'git+https://github.com/enzet/map-machine')
import map_machine.main # we only ever sub-process this out via map_machine.main.__file__

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
  with open(map_state_csv, 'a') as fd:
    fd.write('{},{},{},{}\n'.format(name, timestamp, lat, lon))

def get_pos_reps():
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

def call_map_machine(*args):
  subprocess.run([
    sys.executable, map_machine.main.__file__, *args
  ])

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

async def http_map_req_handler(req):
  #map_png = os.path.join('out', 'map.png')
  map_svg = os.path.join('out', 'map.svg')

  # If map is old, re-render
  if not os.path.exists(map_svg) or int(time.time()) - os.path.getmtime(map_svg) > 4:
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
    min_lat *= 0.90 if min_lat > 0 else 1.10
    max_lat *= 1.10 if max_lat > 0 else 0.90
    min_lon *= 0.90
    max_lon *= 1.10

    call_map_machine(
      'render', '-b={},{},{},{}'.format(min_lon, min_lat, max_lon, max_lat), '--output={}'.format(map_svg),
    )

  # Return file 
  return aiohttp.web.FileResponse(map_svg)


def main(args=sys.argv):

  # prep work to avoid re-doing it later
  os.makedirs(os.path.dirname(map_state_csv), exist_ok=True)

  cert_file, key_file = get_ssl_cert_and_key_or_generate()

  server = aiohttp.web.Application()

  server.add_routes([
    aiohttp.web.get('/', http_file_req_handler),
    aiohttp.web.get('/index.html', http_file_req_handler),
    aiohttp.web.get('/ws', ws_req_handler),
    aiohttp.web.get('/map', http_map_req_handler),
  ])


  ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
  ssl_ctx.load_cert_chain(cert_file, key_file)

  port = int(os.environ.get('PORT', '4430'))

  print('Your LAN ip address is: https://{}:{}/'.format(get_local_ip(), port))

  aiohttp.web.run_app(server, ssl_context=ssl_ctx, port=port)


if __name__ == '__main__':
  main()

