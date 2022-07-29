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

# Globals
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
    host, port = peername

  print('ws req from {}'.format(host))

  ws = aiohttp.web.WebSocketResponse()
  await ws.prepare(req)

  all_websockets.append(ws)

  await ws.send_str('set_my_name("{}")'.format(host))

  async for msg in ws:
    if msg.type == aiohttp.WSMsgType.TEXT:
      print('WS From {}: {}'.format(host, msg.data))
      
      if msg.data.startswith('message='):
        continue

      # Broadcast to everyone else
      # with CodeTimer('Broadcast to everyone else', unit='ms'):
      #   await asyncio.gather(*[ maybe_await(lambda: w.send_str(msg.data)) for w in all_websockets if w != ws])
      await asyncio.gather(*[ maybe_await(lambda: w.send_str(msg.data)) for w in all_websockets if w != ws])
      
    elif msg.type == aiohttp.WSMsgType.ERROR:
      print('ws connection closed with exception {}'.format(ws.exception()))

  all_websockets.remove(ws)

  await asyncio.gather(*[ maybe_await(lambda: w.send_str('remove_camera_named("{}")'.format(host))) for w in all_websockets])

  return ws


def main(args=sys.argv):

  cert_file, key_file = get_ssl_cert_and_key_or_generate()

  server = aiohttp.web.Application()

  server.add_routes([
    aiohttp.web.get('/', http_file_req_handler),
    aiohttp.web.get('/ws', ws_req_handler),
  ])


if __name__ == '__main__':
  main()