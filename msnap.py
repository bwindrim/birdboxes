# https://martinheinz.dev/blog/86
import sys
import os
import subprocess
import mastodon
from mastodon import Mastodon
import picamera
from picamera import PiCamera
from time import sleep
from datetime import datetime

if len(sys.argv) <= 1:
    platform = "testbed"
    prefix = "TB"
else:
    platform = sys.argv[1].lower()
    prefix = ""
    for c in sys.argv[1]:
        if c.isupper() or c.isdigit():
            prefix += c

# Ensure that any files we create are read-only
os.umask (0o222)

dtime = datetime.now()
filename = prefix + "_" + dtime.isoformat(timespec='seconds') + ".jpg"
local_dir = "/mnt/local/timelapse"
remote_dir = "/mnt/remote/" + platform + "/timelapse"
local_file = local_dir + "/" + filename
remote_file = remote_dir + "/" + filename

m = Mastodon(access_token="PUcFR0KDRa9M36DaJ1ZkSSXljPj1lK91pkqAMnDyYHQ", api_base_url="https://botsin.space")

with PiCamera() as camera:
    camera.resolution = (640, 480)
    camera.capture(local_file)
    camera.stop_preview()

# copy the local file over NFS, if the destination directory exists
if os.path.isdir(remote_dir):
    subprocess.run(["/usr/bin/cp", "-p", local_file, remote_file])

metadata = m.media_post(local_file, "image/jpg")
# Response format: https://mastodonpy.readthedocs.io/en/stable/#media-dicts
if len(sys.argv) <= 2:
    message = "Another post from " + platform + ": " + filename
else:
    message = sys.argv[2]

m.status_post(message, media_ids=metadata["id"])
