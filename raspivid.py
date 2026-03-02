import os
from picamera import PiCamera
from datetime import datetime

# Ensure that any files we create are read-only
os.umask (0o222)

# Get the filename for the local video file
dtime = datetime.now()
filename = prefix + "_" + dtime.isoformat(timespec='seconds') + ".h264"
local_dir = "/mnt/local/video"
#remote_dir = "/mnt/remote/" + platform + "/video"
local_file = local_dir + "/" + filename
#remote_file = remote_dir + "/" + filename

# Open a file object for writing to stdout (binary)
with os.open(1, 'wb') as stdout:

    # Create a camera object and set it up for video recording
    with PiCamera() as camera:
        camera.resolution = (640, 480)
        camera.awb_mode = 'off'
        camera.awb_gains = (1.0, 1.0)

        # Start recording video to local file
        camera.start_recording(local_file, format='h264')
        
        # Open the local video file for reading (binary)
        with os.open(local_file, 'rb') as file:
            # Loop, copying data from the file to stdout, until EOF on stdout
            while True:
                buff = file.read(1024)
                try:
                    stdout.write(buff)
                except OSError: # catch EOF on stdout...
                    break       # ...and exit the loop
                camera.wait_recording() # default timeout is zero
            # Stop recording
            camera.stop_recording()

# Finish
